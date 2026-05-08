import re
import logging
import requests
from urllib.parse import urlencode, quote

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

VALID_PREFIXES = {'0412', '0414', '0416', '0424', '0426'}


def clean_phone(raw):
    if not raw:
        return None, "Vacio"
    digits = re.sub(r'\D', '', str(raw))
    if digits.startswith('58') and len(digits) == 12:
        digits = '0' + digits[2:]
    if len(digits) == 10 and digits[0] == '4':
        digits = '0' + digits
    if len(digits) != 11:
        return None, f"'{raw}' tiene {len(digits)} digitos (se esperan 11)"
    if digits[:4] not in VALID_PREFIXES:
        return None, f"'{raw}' prefijo {digits[:4]} invalido"
    return digits, None


def get_sms_credentials(env):
    """
    Funcion helper que obtiene las credenciales SMS desde dos fuentes:
    1. Modelo interconectados.config (fuente principal, registro permanente)
    2. ir.config_parameter (fallback y cache de sincronizacion)
    Lanza UserError si no hay credenciales configuradas.
    """
    # Fuente 1: modelo permanente interconectados.config
    config = env['interconectados.config'].sudo().search([], limit=1)
    if config and config.api_user and config.api_password:
        return config.api_user, config.api_password, config.api_url or 'https://www.interconectados.net/api2/'

    # Fuente 2: ir.config_parameter (compatibilidad con versiones anteriores)
    ICP = env['ir.config_parameter'].sudo()
    user = ICP.get_param('interconectados.api_user', '')
    password = ICP.get_param('interconectados.api_password', '')
    url = ICP.get_param('interconectados.api_url', 'https://www.interconectados.net/api2/')

    if user and password:
        return user, password, url

    raise UserError(
        "No se encontraron credenciales configuradas.\n\n"
        "Ve a SMS Marketing → Configuracion, ingresa tu usuario y clave "
        "de Interconectados.net y guarda el formulario."
    )


class InterconectadosSMSWizard(models.TransientModel):
    _name = 'interconectados.sms.wizard'
    _description = 'Enviar SMS via Interconectados.net'

    # Campos de credenciales — solo para uso interno, NO visibles en la vista
    api_user = fields.Char()
    api_password = fields.Char()
    api_url = fields.Char()

    # Plantilla
    template_id = fields.Many2one('interconectados.sms.template', string="Plantilla")

    # Destinatario
    phone_numbers = fields.Char(
        string="Telefono(s)",
        required=True,
        placeholder="04141234567  o  04141234567,04161234567",
    )
    partner_id = fields.Many2one('res.partner', string="Contacto")
    move_id = fields.Many2one('account.move', string="Factura")

    # Mensaje
    message = fields.Text(string="Mensaje", required=True)
    char_count = fields.Integer(compute='_compute_char_count')
    sms_count = fields.Integer(compute='_compute_char_count')

    # Resultado
    result_message = fields.Text(string="Resultado", readonly=True)

    @api.depends('message')
    def _compute_char_count(self):
        for rec in self:
            n = len(rec.message or '')
            rec.char_count = n
            rec.sms_count = (
                0 if n == 0 else
                1 if n <= 160 else
                2 if n <= 305 else
                3 if n <= 457 else 4
            )

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            record = self.partner_id or self.move_id or None
            self.message = self.template_id.render_body(record)

    def _parse_phones(self):
        tokens = re.split(r'[,;\s]+', self.phone_numbers or '')
        valids, errors = [], []
        for t in tokens:
            t = t.strip()
            if not t:
                continue
            clean, err = clean_phone(t)
            if clean:
                if clean not in valids:
                    valids.append(clean)
            else:
                errors.append(err)
        return valids, errors

    def _send_request(self, phones, message, user, password, url):
        params = {
            'phonenumber': ','.join(phones),
            'text': message,
            'user': user,
            'password': password,
        }
        full_url = f"{url.rstrip('/')}/?{urlencode(params, quote_via=quote)}"
        _logger.info("Interconectados SMS — %s", full_url.replace(password, '***'))
        try:
            resp = requests.get(full_url, timeout=30)
            return resp.status_code, resp.text.strip(), None
        except Exception as e:
            return None, None, str(e)

    def _interpret(self, code, body, net_err):
        if net_err:
            return False, f"Error de red: {net_err}"
        msgs = {
            200: "SMS enviado correctamente",
            400: "Error 400: Falta el texto",
            401: "Error 401: Credenciales invalidas",
            402: "Error 402: Creditos insuficientes",
            403: "Error 403: Cuenta inactiva",
            405: "Error 405: Falta numero destinatario",
            502: "Error 502: Maximo 500 destinatarios",
        }
        return code == 200, msgs.get(code, f"Codigo {code}: {body}")

    def _log_history(self, phones, message, ok, detail, code):
        for phone in phones:
            self.env['interconectados.sms.history'].create({
                'phone': phone,
                'message': message,
                'state': 'sent' if ok else 'error',
                'error_message': None if ok else detail,
                'partner_id': self.partner_id.id if self.partner_id else False,
                'move_id': self.move_id.id if self.move_id else False,
                'response_code': str(code) if code else 'NET_ERROR',
            })

    def action_send_sms(self):
        self.ensure_one()
        if not self.message or not self.message.strip():
            raise UserError("El mensaje no puede estar vacio.")

        # Obtener credenciales desde el modelo permanente (nunca del wizard)
        user, password, url = get_sms_credentials(self.env)

        phones, errors = self._parse_phones()
        lines = []
        if errors:
            lines.append("Numeros con error (no enviados):")
            lines.extend(f"  - {e}" for e in errors)
        if not phones:
            raise UserError("No hay numeros validos.\n" + "\n".join(lines))

        code, body, net_err = self._send_request(phones, self.message.strip(), user, password, url)
        ok, detail = self._interpret(code, body, net_err)
        self._log_history(phones, self.message.strip(), ok, detail, code)

        lines += [f"Destinatarios: {', '.join(phones)}", detail]
        self.result_message = "\n".join(lines)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Resultado del envio SMS',
                'message': "\n".join(lines),
                'type': 'success' if ok else 'danger',
                'sticky': True,
            },
        }

    def action_check_balance(self):
        self.ensure_one()
        user, password, url = get_sms_credentials(self.env)
        params = {'user': user, 'password': password, 'get': 'credits'}
        req_url = f"{url.rstrip('/')}/get.asp?{urlencode(params)}"
        try:
            resp = requests.get(req_url, timeout=30)
            msg = f"Creditos disponibles: {resp.text.strip()}" if resp.status_code == 200 \
                else f"Error {resp.status_code}: {resp.text}"
            t = 'success' if resp.status_code == 200 else 'danger'
        except Exception as e:
            msg, t = f"Error de conexion: {e}", 'danger'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'Consulta de creditos', 'message': msg, 'type': t, 'sticky': True},
        }
