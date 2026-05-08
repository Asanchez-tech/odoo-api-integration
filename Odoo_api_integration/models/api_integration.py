from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import json
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

class APIIntegrationLog(models.Model):
    _name = 'api.integration.log'
    _description = 'API Integration Logs'
    _order = 'create_date desc'
    
    api_key_id = fields.Many2one(
        'api.integration.key', 
        string='API Key',
        ondelete='cascade',
        required=True
    )
    company_id = fields.Many2one(
        'res.company', 
        string='Company',
        related='api_key_id.company_id',
        store=True,
        readonly=True
    )
    endpoint = fields.Char(string='Endpoint', required=True, help="API endpoint that was called")
    method = fields.Char(string='HTTP Method', required=True, help="HTTP method used (GET, POST, etc.)")
    request_data = fields.Text(string='Request Data', help="Data sent in the request")
    response_data = fields.Text(string='Response Data', help="Data returned in the response")
    status_code = fields.Integer(string='Status Code', required=True, help="HTTP status code returned")
    ip_address = fields.Char(string='IP Address', required=True, help="IP address of the client")
    user_id = fields.Many2one(
        'res.users', 
        string='User',
        related='api_key_id.user_id',
        store=True,
        readonly=True
    )
    duration = fields.Float(string='Duration (ms)', help="Request duration in milliseconds")
    error_message = fields.Text(string='Error Message', help="Error message if the request failed")
    
    # Campos calculados
    is_success = fields.Boolean(
        string='Success', 
        compute='_compute_is_success',
        store=True
    )
    request_size = fields.Integer(
        string='Request Size (bytes)',
        compute='_compute_sizes',
        store=True
    )
    response_size = fields.Integer(
        string='Response Size (bytes)',
        compute='_compute_sizes',
        store=True
    )
    
    @api.depends('status_code')
    def _compute_is_success(self):
        """Calcular si la solicitud fue exitosa"""
        for record in self:
            record.is_success = 200 <= record.status_code < 400
    
    @api.depends('request_data', 'response_data')
    def _compute_sizes(self):
        """Calcular tamaños de request y response"""
        for record in self:
            record.request_size = len(record.request_data or '')
            record.response_size = len(record.response_data or '')
    
    def name_get(self):
        """Nombre personalizado para los logs"""
        result = []
        for log in self:
            name = f"{log.endpoint} - {log.status_code} - {log.create_date.strftime('%Y-%m-%d %H:%M')}"
            result.append((log.id, name))
        return result

class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    def get_available_for_sale_data(self, company_id=None):
        """
        Obtener datos de productos disponibles para venta
        Filtrados por compañía si se especifica
        """
        try:
            # Filtrar por compañía si se especifica
            if company_id:
                products = self.filtered(lambda p: p.company_id.id == company_id or not p.company_id)
            else:
                products = self
            
            product_data = []
            for product in products:
                # Obtener stock disponible considerando la compañía
                try:
                    qty_available = product.with_context(
                        force_company=company_id
                    ).qty_available if company_id else product.qty_available
                    
                    virtual_available = product.with_context(
                        force_company=company_id
                    ).virtual_available if company_id else product.virtual_available
                except:
                    qty_available = product.qty_available
                    virtual_available = product.virtual_available
                
                product_info = {
                    'id': product.id,
                    'name': product.name,
                    'default_code': product.default_code or '',
                    'barcode': product.barcode or '',
                    'list_price': float(product.list_price),
                    'standard_price': float(product.standard_price),
                    'qty_available': float(qty_available),
                    'virtual_available': float(virtual_available),
                    'incoming_qty': float(product.incoming_qty),
                    'outgoing_qty': float(product.outgoing_qty),
                    'categ_id': product.categ_id.id if product.categ_id else False,
                    'categ_name': product.categ_id.name if product.categ_id else '',
                    'image_1920': self._get_image_data(product),
                    'description_sale': product.description_sale or '',
                    'uom_id': product.uom_id.id if product.uom_id else False,
                    'uom_name': product.uom_id.name if product.uom_id else '',
                    'company_id': product.company_id.id if product.company_id else False,
                    'company_name': product.company_id.name if product.company_id else 'All Companies',
                    'sale_ok': product.sale_ok,
                    'purchase_ok': product.purchase_ok,
                    'type': product.type,
                    'weight': float(product.weight) if product.weight else 0.0,
                    'volume': float(product.volume) if product.volume else 0.0,
                }
                product_data.append(product_info)
            
            return product_data
            
        except Exception as e:
            _logger.error(f"Error in get_available_for_sale_data: {str(e)}")
            raise
    
    def _get_image_data(self, product):
        """Obtener datos de imagen de forma segura"""
        try:
            if product.image_1920:
                return product.image_1920.decode('utf-8')
            return False
        except:
            return False

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    api_origin = fields.Char(string='API Origin', help="Indicate if this order was created via API")
    
    @api.model
    def create_from_api(self, order_data, api_key):
        """
        Crear pedido de venta desde API con control de compañía
        y validaciones de seguridad
        """
        try:
            _logger.info(f"Creating order from API for company {api_key.company_id.name}")
            
            # Validar datos del pedido
            if not order_data.get('partner_id'):
                raise ValidationError("Partner ID is required")
            
            if not order_data.get('order_lines') or not isinstance(order_data['order_lines'], list):
                raise ValidationError("Order lines are required and must be a list")
            
            # Verificar que el partner pertenezca a la misma compañía o sea global
            partner = self.env['res.partner'].browse(order_data['partner_id'])
            if not partner.exists():
                raise ValidationError(f"Partner with ID {order_data['partner_id']} does not exist")
            
            if partner.company_id and partner.company_id.id != api_key.company_id.id:
                raise ValidationError(
                    f"Partner belongs to company '{partner.company_id.name}' "
                    f"but API key is for company '{api_key.company_id.name}'"
                )
            
            # Preparar datos del pedido con la compañía de la API key
            vals = {
                'partner_id': order_data['partner_id'],
                'company_id': api_key.company_id.id,
                'date_order': fields.Datetime.now(),
                'origin': f"API Integration - {api_key.name}",
                'api_origin': api_key.name,
                'client_order_ref': order_data.get('client_order_ref', ''),
                'note': order_data.get('note', ''),
                'require_payment': order_data.get('require_payment', False),
            }
            
            # Crear pedido en el contexto de la compañía correcta
            order = self.with_company(api_key.company_id.id).create(vals)
            _logger.info(f"Order {order.name} created via API")
            
            # Procesar líneas del pedido
            order_line_obj = self.env['sale.order.line'].with_company(api_key.company_id.id)
            for line_index, line_data in enumerate(order_data['order_lines']):
                if not line_data.get('product_id'):
                    raise ValidationError(f"Product ID is required for line {line_index + 1}")
                
                # Verificar que el producto exista
                product = self.env['product.product'].browse(line_data['product_id'])
                if not product.exists():
                    raise ValidationError(f"Product with ID {line_data['product_id']} does not exist")
                
                # Verificar que el producto pertenezca a la misma compañía o sea global
                if product.company_id and product.company_id.id != api_key.company_id.id:
                    raise ValidationError(
                        f"Product '{product.name}' belongs to company '{product.company_id.name}' "
                        f"but API key is for company '{api_key.company_id.name}'"
                    )
                
                # Verificar que el producto esté disponible para venta
                if not product.sale_ok:
                    raise ValidationError(f"Product '{product.name}' is not available for sale")
                
                # Calcular precio si no se proporciona
                price_unit = line_data.get('price_unit')
                if not price_unit:
                    price_unit = product.list_price
                
                # Preparar valores de la línea
                line_vals = {
                    'order_id': order.id,
                    'product_id': line_data['product_id'],
                    'product_uom_qty': line_data.get('quantity', 1),
                    'price_unit': price_unit,
                    'name': line_data.get('description', product.name),
                    'product_uom': product.uom_id.id,
                }
                
                # Crear línea del pedido
                order_line = order_line_obj.create(line_vals)
                _logger.info(f"Order line created: {order_line.product_id.name} x {order_line.product_uom_qty}")
            
            # Confirmar pedido si se solicita
            if order_data.get('auto_confirm', False):
                order.with_company(api_key.company_id.id).action_confirm()
                _logger.info(f"Order {order.name} confirmed via API")
            
            return order
            
        except Exception as e:
            _logger.error(f"Error creating order from API: {str(e)}")
            raise

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    def get_partner_data_for_api(self, company_id=None):
        """
        Obtener datos de partners filtrados por compañía
        para uso en API
        """
        try:
            # Filtrar por compañía si se especifica
            if company_id:
                partners = self.filtered(lambda p: p.company_id.id == company_id or not p.company_id)
            else:
                partners = self
            
            partner_data = []
            for partner in partners:
                partner_info = {
                    'id': partner.id,
                    'name': partner.name,
                    'email': partner.email or '',
                    'phone': partner.phone or '',
                    'street': partner.street or '',
                    'street2': partner.street2 or '',
                    'city': partner.city or '',
                    'state_id': partner.state_id.id if partner.state_id else False,
                    'state_name': partner.state_id.name if partner.state_id else '',
                    'country_id': partner.country_id.id if partner.country_id else False,
                    'country_name': partner.country_id.name if partner.country_id else '',
                    'zip': partner.zip or '',
                    'is_company': partner.is_company,
                    'customer_rank': partner.customer_rank,
                    'supplier_rank': partner.supplier_rank,
                    'company_id': partner.company_id.id if partner.company_id else False,
                    'company_name': partner.company_id.name if partner.company_id else 'All Companies',
                    'active': partner.active,
                    'lang': partner.lang or '',
                }
                partner_data.append(partner_info)
            
            return partner_data
            
        except Exception as e:
            _logger.error(f"Error in get_partner_data_for_api: {str(e)}")
            raise

class ProductCategory(models.Model):
    _inherit = 'product.category'
    
    def get_category_data_for_api(self):
        """Obtener datos de categorías para API"""
        category_data = []
        for category in self:
            category_data.append({
                'id': category.id,
                'name': category.name,
                'parent_id': category.parent_id.id if category.parent_id else False,
                'parent_name': category.parent_id.name if category.parent_id else '',
            })
        return category_data
