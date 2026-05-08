import re
import csv
import base64
import logging
import io
import requests
from urllib.parse import urlencode, quote

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

VALID_PREFIXES = {'0412', '0414', '0416', '0424', '0426'}


def get_sms_credentials(env):
    """
    Obtiene credenciales SMS desde el modelo permanente interconectados.config.
    Fallback a ir.config_parameter para compatibilidad.
    """
    config = env['interconectados.config'].sudo().search([], limit=1)
    if config and config.api_user and config.api_password:
        return (
            config.api_user,
            config.api_password,
            config.api_url or 'https://www.interconectados.net/api2/'
        )
    ICP = env['ir.config_parameter'].sudo()
    user = ICP.get_param('interconectados.api_user', '')
    password = ICP.get_param('interconectados.api_password', '')
    url = ICP.get_param('interconectados.api_url', 'https://www.interconectados.net/api2/')
    if user and password:
        return user, password, url
    raise UserError(
        "No se encontraron credenciales configuradas.\n"
        "Ve a SMS Marketing → Configuracion e ingresa usuario y clave."
    )


def clean_phone(raw):
    if not raw:
        return None, "Vacio"
    digits = re.sub(r'\D', '', str(raw))
    if digits.startswith('58') and len(digits) == 12:
        digits = '0' + digits[2:]
    if len(digits) == 10 and digits[0] == '4':
        digits = '0' + digits
    if len(digits) != 11:
        return None, f"{raw} -> {len(digits)} digitos (se esperan 11)"
    if digits[:4] not in VALID_PREFIXES:
        return None, f"{raw} -> prefijo {digits[:4]} invalido"
    return digits, None


class SmsCampaign(models.Model):
    _name = 'interconectados.sms.campaign'
    _description = 'Campana de SMS Marketing'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_created desc'

    name = fields.Char(string="Nombre de la campana", required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('scheduled', 'Programada'),
        ('running', 'Enviando'),
        ('done', 'Completada'),
        ('error', 'Con errores'),
    ], string="Estado", default='draft', readonly=True, tracking=True)

    template_id = fields.Many2one('interconectados.sms.template', string="Plantilla")
    message = fields.Text(string="Mensaje", required=True)

    recipient_type = fields.Selection([
        ('manual', 'Numeros manuales'),
        ('file', 'Cargar archivo (CSV/TXT)'),
        ('partners', 'Contactos de Odoo'),
    ], string="Tipo de destinatarios", default='manual', required=True)

    phone_numbers_raw = fields.Text(string="Numeros de telefono")
    upload_file = fields.Binary(string="Archivo CSV/TXT")
    upload_filename = fields.Char(string="Nombre del archivo")
    partner_ids = fields.Many2many('res.partner', string="Contactos")
    partner_domain = fields.Char(string="Filtro de contactos", default="[]")

    phone_list = fields.Text(string="Lista final de numeros", readonly=True)
    total_recipients = fields.Integer(string="Total destinatarios", readonly=True)
    valid_count = fields.Integer(string="Validos", readonly=True)
    invalid_count = fields.Integer(string="Invalidos", readonly=True)
    invalid_detail = fields.Text(string="Detalle de invalidos", readonly=True)

    scheduled = fields.Boolean(string="Programar envio")
    scheduled_date = fields.Datetime(string="Fecha y hora de envio")

    date_created = fields.Datetime(string="Creada el", default=fields.Datetime.now, readonly=True)
    date_sent = fields.Datetime(string="Enviada el", readonly=True)
    sent_count = fields.Integer(string="Enviados", readonly=True)
    error_count = fields.Integer(string="Errores", readonly=True)

    history_ids = fields.One2many(
        'interconectados.sms.history', 'campaign_id', string="Historial"
    )
    history_count = fields.Integer(compute='_compute_history_count')

    def _compute_history_count(self):
        for rec in self:
            rec.history_count = len(rec.history_ids)

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.message = self.template_id.body

    # ── Procesar destinatarios ──────────────────────────────────────────────
    def action_process_recipients(self):
        self.ensure_one()
        phones_raw = []

        if self.recipient_type == 'manual':
            if not self.phone_numbers_raw:
                raise UserError("Escribe al menos un numero de telefono.")
            phones_raw = re.split(r'[,;\n\r\s]+', self.phone_numbers_raw)
        elif self.recipient_type == 'file':
            if not self.upload_file:
                raise UserError("Sube un archivo CSV o TXT con los numeros.")
            phones_raw = self._parse_file()
        elif self.recipient_type == 'partners':
            partners = self.partner_ids
            if not partners and self.partner_domain:
                try:
                    domain = eval(self.partner_domain)
                    partners = self.env['res.partner'].search(domain)
                except Exception:
                    raise UserError("El filtro de contactos no es valido.")
            if not partners:
                raise UserError("No hay contactos seleccionados.")
            for p in partners:
                phones_raw.append(p.mobile or p.phone or '')

        phones_raw = [p.strip() for p in phones_raw if p.strip()]
        valids, invalids, errors = [], [], []

        for raw in phones_raw:
            clean, err = clean_phone(raw)
            if clean:
                if clean not in valids:
                    valids.append(clean)
            else:
                invalids.append(raw)
                errors.append(err)

        self.write({
            'phone_list': ','.join(valids),
            'total_recipients': len(phones_raw),
            'valid_count': len(valids),
            'invalid_count': len(invalids),
            'invalid_detail': '\n'.join(errors) if errors else False,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Destinatarios procesados',
                'message': f"Validos: {len(valids)} | Invalidos: {len(invalids)}",
                'type': 'success' if valids else 'danger',
                'sticky': False,
            },
        }

    def _parse_file(self):
        try:
            content = base64.b64decode(self.upload_file).decode('utf-8', errors='replace')
        except Exception as e:
            raise UserError(f"No se pudo leer el archivo: {e}")
        phones = []
        fname = (self.upload_filename or '').lower()
        if fname.endswith('.csv'):
            reader = csv.reader(io.StringIO(content))
            for row in reader:
                for cell in row:
                    if cell.strip():
                        phones.append(cell.strip())
        else:
            for line in content.splitlines():
                for token in re.split(r'[,;]+', line):
                    if token.strip():
                        phones.append(token.strip())
        return phones

    def _get_credentials(self):
        return get_sms_credentials(self.env)

    def _send_batch(self, phones, message, user, password, api_url):
        params = {
            'phonenumber': ','.join(phones),
            'text': message,
            'user': user,
            'password': password,
        }
        url = f"{api_url.rstrip('/')}/?{urlencode(params, quote_via=quote)}"
        _logger.info("Interconectados SMS — lote %d numeros: %s",
                     len(phones), url.replace(password, '***'))
        try:
            resp = requests.get(url, timeout=30)
            return resp.status_code, resp.text.strip(), None
        except Exception as e:
            return None, None, str(e)

    def _interpret(self, status_code, body, net_error):
        if net_error:
            return False, net_error
        msgs = {
            200: "Enviado correctamente",
            400: "Error 400: Falta el texto",
            401: "Error 401: Credenciales invalidas",
            402: "Error 402: Creditos insuficientes",
            403: "Error 403: Cuenta inactiva",
            405: "Error 405: Falta destinatario",
            501: "Error 501: Tipo de cuenta invalido",
            502: "Error 502: Demasiados destinatarios",
        }
        return status_code == 200, msgs.get(status_code, f"Codigo {status_code}: {body}")

    def _do_send(self):
        """
        Logica pura de envio — sin commit() manual ni retorno de accion UI.
        El cron de Odoo maneja su propia transaccion; hacer commit() dentro
        del cron rompe ese manejo y causa que el envio no se complete.
        Retorna (sent_count, error_count).
        """
        user, password, api_url = self._get_credentials()
        phones = [p for p in (self.phone_list or '').split(',') if p.strip()]

        # Marcar como running SIN commit — el cron hara commit al terminar
        self.write({'state': 'running'})

        sent, errors = 0, 0
        batch_size = 500

        for i in range(0, len(phones), batch_size):
            batch = phones[i:i + batch_size]
            code, body, net_err = self._send_batch(
                batch, self.message, user, password, api_url
            )
            ok, detail = self._interpret(code, body, net_err)

            for phone in batch:
                self.env['interconectados.sms.history'].create({
                    'phone': phone,
                    'message': self.message,
                    'state': 'sent' if ok else 'error',
                    'error_message': None if ok else detail,
                    'campaign_id': self.id,
                    'response_code': str(code) if code else 'NET_ERROR',
                })
            if ok:
                sent += len(batch)
            else:
                errors += len(batch)

        self.write({
            'state': 'done' if errors == 0 else 'error',
            'date_sent': fields.Datetime.now(),
            'sent_count': sent,
            'error_count': errors,
        })
        return sent, errors

    def action_send_now(self):
        """Llamado desde la UI — envia y muestra notificacion."""
        self.ensure_one()
        if not self.phone_list:
            raise UserError("Primero procesa los destinatarios.")
        if not self.message:
            raise UserError("El mensaje no puede estar vacio.")

        sent, errors = self._do_send()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Campana ejecutada',
                'message': f"Enviados: {sent} | Errores: {errors}",
                'type': 'success' if errors == 0 else 'warning',
                'sticky': True,
            },
        }

    def action_schedule(self):
        self.ensure_one()
        if not self.scheduled_date:
            raise UserError("Selecciona la fecha y hora de envio programado.")
        if not self.phone_list:
            raise UserError("Primero procesa los destinatarios.")
        self.write({'state': 'scheduled'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Campana programada',
                'message': f"Se enviara automaticamente el {self.scheduled_date}",
                'type': 'success',
                'sticky': False,
            },
        }

    def action_reset(self):
        self.write({'state': 'draft'})

    def action_view_history(self):
        return {
            'name': f"Historial — {self.name}",
            'type': 'ir.actions.act_window',
            'res_model': 'interconectados.sms.history',
            'view_mode': 'list,form',
            'domain': [('campaign_id', '=', self.id)],
        }

    # ── Cron ───────────────────────────────────────────────────────────────
    @api.model
    def _cron_send_scheduled(self):
        """
        Ejecutado automaticamente cada 15 minutos por el cron de Odoo.

        IMPORTANTE: Este metodo NO hace commit() ni retorna acciones UI.
        El cron de Odoo maneja su propia transaccion completa.
        Cada campana se procesa en un savepoint independiente para que
        un error en una campana no cancele el resto.
        """
        now = fields.Datetime.now()
        campaigns = self.search([
            ('state', '=', 'scheduled'),
            ('scheduled_date', '<=', now),
        ])

        if not campaigns:
            _logger.info("Cron SMS: no hay campanas programadas para enviar")
            return

        _logger.info("Cron SMS: %d campana(s) listas para enviar", len(campaigns))

        for campaign in campaigns:
            # Usar savepoint para aislar cada campana
            # Si una falla, las demas siguen procesandose
            try:
                with self.env.cr.savepoint():
                    _logger.info(
                        "Cron SMS: iniciando campana '%s' (id=%s, destinatarios=%s)",
                        campaign.name, campaign.id, campaign.valid_count
                    )
                    sent, errors = campaign._do_send()
                    _logger.info(
                        "Cron SMS: campana '%s' completada — enviados=%d errores=%d",
                        campaign.name, sent, errors
                    )
            except Exception as e:
                _logger.error(
                    "Cron SMS: fallo en campana '%s' (id=%s): %s",
                    campaign.name, campaign.id, str(e)
                )
                # Marcar como error en un savepoint separado
                try:
                    with self.env.cr.savepoint():
                        campaign.write({'state': 'error'})
                except Exception:
                    pass
