import requests
import logging
from urllib.parse import urlencode
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class InterconectadosConfig(models.Model):
    """
    Modelo permanente singleton para guardar la configuracion SMS.
    Los campos NO son required para permitir crear el registro vacio
    y que el usuario lo llene despues desde la interfaz.
    """
    _name = 'interconectados.config'
    _description = 'Configuracion SMS Interconectados'

    name = fields.Char(default='Configuracion SMS', readonly=True)

    # Sin required=True — el usuario los llena despues de instalar
    api_user = fields.Char(
        string="Usuario API",
        help="Usuario de tu cuenta en interconectados.net",
    )
    api_password = fields.Char(
        string="Clave API",
        help="Contrasena de tu cuenta en interconectados.net",
    )
    api_url = fields.Char(
        string="URL del Gateway",
        default='https://www.interconectados.net/api2/',
    )
    sender_name = fields.Char(
        string="Nombre del remitente",
        help="Opcional: nombre visible como remitente del SMS",
    )
    balance_result = fields.Char(
        string="Creditos disponibles",
        readonly=True,
    )

    @api.model
    def get_singleton(self):
        """Retorna el unico registro, creandolo si no existe."""
        config = self.search([], limit=1)
        if not config:
            config = self.create({
                'name': 'Configuracion SMS',
                'api_url': 'https://www.interconectados.net/api2/',
            })
        return config

    def write(self, vals):
        """Al guardar, sincroniza con ir.config_parameter."""
        res = super().write(vals)
        ICP = self.env['ir.config_parameter'].sudo()
        if 'api_user' in vals:
            ICP.set_param('interconectados.api_user', vals['api_user'] or '')
        if 'api_password' in vals:
            ICP.set_param('interconectados.api_password', vals['api_password'] or '')
        if 'api_url' in vals:
            ICP.set_param('interconectados.api_url',
                          vals['api_url'] or 'https://www.interconectados.net/api2/')
        if 'sender_name' in vals:
            ICP.set_param('interconectados.sender_name', vals.get('sender_name') or '')
        _logger.info("Interconectados SMS: configuracion actualizada")
        return res

    @api.model
    def create(self, vals):
        """Al crear, sincroniza con ir.config_parameter."""
        record = super().create(vals)
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('interconectados.api_user', vals.get('api_user') or '')
        ICP.set_param('interconectados.api_password', vals.get('api_password') or '')
        ICP.set_param('interconectados.api_url',
                      vals.get('api_url') or 'https://www.interconectados.net/api2/')
        ICP.set_param('interconectados.sender_name', vals.get('sender_name') or '')
        return record

    def action_check_balance(self):
        """Consulta creditos y actualiza el campo balance_result."""
        self.ensure_one()
        if not self.api_user or not self.api_password:
            self.balance_result = "Ingresa usuario y clave antes de consultar"
            return
        params = {
            'user': self.api_user,
            'password': self.api_password,
            'get': 'credits',
        }
        url = f"{(self.api_url or '').rstrip('/')}/get.asp?{urlencode(params)}"
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                self.balance_result = f"Creditos disponibles: {resp.text.strip()}"
            elif resp.status_code == 401:
                self.balance_result = "Error 401: Usuario o clave incorrectos"
            elif resp.status_code == 403:
                self.balance_result = "Error 403: Cuenta inactiva"
            else:
                self.balance_result = f"Error {resp.status_code}: {resp.text.strip()}"
        except Exception as e:
            self.balance_result = f"Error de conexion: {e}"
