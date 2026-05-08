from odoo import models, fields, api
from odoo.exceptions import ValidationError, AccessError
import secrets
import string
import logging

_logger = logging.getLogger(__name__)

class APIKey(models.Model):
    _name = 'api.integration.key'
    _description = 'API Integration Keys'
    _rec_name = 'name'
    _order = 'created_at desc'
    
    name = fields.Char(string='Key Name', required=True, help="Descriptive name for this API key")
    key = fields.Char(string='API Key', copy=False, help="Secure API key for authentication")
    user_id = fields.Many2one(
        'res.users', 
        string='Associated User', 
        required=True,
        default=lambda self: self.env.user.id,
        help="User associated with this API key"
    )
    company_id = fields.Many2one(
        'res.company', 
        string='Company', 
        required=True,
        default=lambda self: self.env.company.id,
        help="Company that this API key can access"
    )
    active = fields.Boolean(string='Active', default=True, help="Whether this API key is active")
    expiration_date = fields.Datetime(
        string='Expiration Date', 
        help="Date when this API key expires (optional)"
    )
    permissions = fields.Selection([
        ('read_only', 'Read Only'),
        ('read_write', 'Read and Write'),
        ('full_access', 'Full Access'),
    ], string='Permissions', default='read_only', required=True, help="Access permissions for this API key")
    
    # Campos de auditoría
    created_at = fields.Datetime(string='Created At', default=fields.Datetime.now, readonly=True)
    last_used = fields.Datetime(string='Last Used', readonly=True)
    usage_count = fields.Integer(string='Usage Count', default=0, readonly=True)
    
    # Restricciones de acceso
    allowed_models = fields.Many2many(
        'ir.model', 
        string='Allowed Models',
        relation='api_key_model_rel',
        column1='key_id',
        column2='model_id',
        help="Models that this API key can access. Leave empty for all models."
    )
    ip_whitelist = fields.Text(
        string='IP Whitelist',
        help="Comma-separated list of allowed IP addresses. Leave empty to allow all IPs."
    )
    
    _sql_constraints = [
        ('key_unique', 'UNIQUE(key)', 'API Key must be unique!'),
    ]
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate secure API keys in batch"""
        for vals in vals_list:
            if 'key' not in vals or not vals['key']:
                # Generar una clave segura automáticamente
                alphabet = string.ascii_letters + string.digits
                vals['key'] = 'odoo_api_' + ''.join(secrets.choice(alphabet) for _ in range(50))
            
            # Forzar la compañía del usuario actual si no se especifica
            if 'company_id' not in vals:
                vals['company_id'] = self.env.company.id
                
        result = super().create(vals_list)
        for record in result:
            _logger.info(f"API key created: {record.name} for company {record.company_id.name}")
        return result
    
    def write(self, vals):
        """Log changes to API keys"""
        result = super().write(vals)
        if 'active' in vals:
            status = "activated" if vals['active'] else "deactivated"
            for record in self:
                _logger.info(f"API key {record.name} {status}")
        return result
    
    def unlink(self):
        """Log deletion of API keys"""
        key_names = [key.name for key in self]
        result = super().unlink()
        for name in key_names:
            _logger.info(f"API key {name} deleted")
        return result
    
    def validate_key(self, key, ip_address=None):
        """Validar la clave API"""
        self.ensure_one()
        
        # Verificar si está activa
        if not self.active:
            raise ValidationError("API key is not active")
        
        # Verificar expiración
        if self.expiration_date and self.expiration_date < fields.Datetime.now():
            raise ValidationError("API key has expired")
        
        # Verificar IP si está configurada
        if self.ip_whitelist and ip_address:
            allowed_ips = [ip.strip() for ip in self.ip_whitelist.split(',') if ip.strip()]
            if ip_address not in allowed_ips:
                raise ValidationError(f"IP address {ip_address} not allowed. Allowed IPs: {', '.join(allowed_ips)}")
        
        # Actualizar estadísticas de uso
        self.write({
            'last_used': fields.Datetime.now(),
            'usage_count': self.usage_count + 1
        })
        
        return True
    
    def regenerate_key(self):
        """Regenerar la clave API"""
        self.ensure_one()
        alphabet = string.ascii_letters + string.digits
        new_key = 'odoo_api_' + ''.join(secrets.choice(alphabet) for _ in range(50))
        self.key = new_key
        
        _logger.info(f"API key regenerated for {self.name}")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'API Key Regenerated',
                'message': 'New API key has been generated successfully',
                'type': 'success',
                'sticky': False,
            }
        }
    
    def copy_key(self):
        """Mostrar la clave API en una notificación clara"""
        self.ensure_one()
        
        if not self.key:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'No API key available to show',
                    'type': 'danger',
                    'sticky': False,
                }
            }
        
        _logger.info(f"User viewed API key for {self.name}")
        
        # Mensaje claro sin HTML
        message = f"CLAVE API: {self.key}\n\n📋 Copia esta clave completa\n🔐 Úsala en el header: X-API-Key\n⚠️  Mantén la clave segura"
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'🔑 API Key - {self.name}',
                'message': message,
                'type': 'warning',
                'sticky': True,
            }
        }
    
    def action_view_logs(self):
        """Ver logs de esta API key"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'API Logs',
            'res_model': 'api.integration.log',
            'view_mode': 'list,form',
            'domain': [('api_key_id', '=', self.id)],
            'context': {'create': False},
        }
    
    @api.constrains('expiration_date')
    def _check_expiration_date(self):
        """Validar que la fecha de expiración sea futura"""
        for record in self:
            if record.expiration_date and record.expiration_date < fields.Datetime.now():
                raise ValidationError("Expiration date must be in the future")
    
    @api.constrains('user_id', 'company_id')
    def _check_user_company(self):
        """Validar que el usuario tenga acceso a la compañía"""
        for record in self:
            if record.user_id and record.company_id:
                user_companies = record.user_id.company_ids
                if record.company_id not in user_companies:
                    raise ValidationError(
                        f"User {record.user_id.name} doesn't have access to company {record.company_id.name}"
                    )
    
    @api.constrains('key')
    def _check_key_not_empty(self):
        """Validar que la clave no esté vacía después de la creación"""
        for record in self:
            if not record.key:
                raise ValidationError("API Key cannot be empty")
