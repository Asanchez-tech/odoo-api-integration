from odoo import http
from odoo.http import request, Response
from odoo import fields
import json
import time
import logging
from functools import wraps

_logger = logging.getLogger(__name__)

# ==============================================================================
# FUNCIONES AUXILIARES - VERSIÓN CORREGIDA
# ==============================================================================

def _validate_api_key(api_key_header):
    """Validar API Key - VERSIÓN CORREGIDA"""
    if not api_key_header:
        _logger.warning("API key header is empty")
        return False, "API key is required"
    
    try:
        # Limpiar la clave
        api_key_clean = api_key_header.strip()
        _logger.info(f"Validating API key: {api_key_clean[:30]}...")
        
        # Buscar la clave API
        key_record = request.env['api.integration.key'].sudo().search([
            ('key', '=', api_key_clean),
            ('active', '=', True)
        ], limit=1)
        
        _logger.info(f"Found {len(key_record)} records for API key")
        
        if not key_record:
            # Log adicional para debug
            all_keys = request.env['api.integration.key'].sudo().search([], limit=5)
            _logger.warning(f"Available keys in DB: {[(k.name, k.key[:20] + '...' if k.key else 'None') for k in all_keys]}")
            
            return False, "Invalid API key or key not found in database"
        
        key_record = key_record[0]  # Tomar el primer registro
        
        # Verificar expiración
        if key_record.expiration_date and key_record.expiration_date < fields.Datetime.now():
            _logger.warning(f"API Key expired: {key_record.name}")
            return False, "API key has expired"
        
        # Verificar IP si está configurada
        if key_record.ip_whitelist and key_record.ip_whitelist.strip():
            client_ip = request.httprequest.environ.get('REMOTE_ADDR', '0.0.0.0')
            allowed_ips = [ip.strip() for ip in key_record.ip_whitelist.split(',') if ip.strip()]
            if allowed_ips and client_ip not in allowed_ips:
                _logger.warning(f"IP not allowed: {client_ip} for API Key {key_record.name}")
                return False, f"IP {client_ip} not allowed. Allowed IPs: {', '.join(allowed_ips)}"
        
        _logger.info(f"✅ API Key validated successfully: {key_record.name}")
        return True, key_record
        
    except Exception as e:
        _logger.error(f"❌ Error validating API key: {str(e)}", exc_info=True)
        return False, f"Internal error validating API key: {str(e)}"

def api_auth(required_permission='read_only'):
    """Decorator para autenticación API - VERSIÓN CORREGIDA"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            start_time = time.time()
            
            try:
                # Obtener headers
                api_key_header = request.httprequest.headers.get('X-API-Key')
                client_ip = request.httprequest.environ.get('REMOTE_ADDR', '0.0.0.0')
                
                _logger.info(f"🔑 API Auth - IP: {client_ip}, X-API-Key: {api_key_header[:30] if api_key_header else 'None'}...")
                
                # Validar API Key
                is_valid, result = _validate_api_key(api_key_header)
                
                if not is_valid:
                    _logger.warning(f"❌ Auth failed: {result}")
                    return error_response(401, result)
                
                key_record = result
                
                # Verificar permisos
                if required_permission == 'read_write' and key_record.permissions == 'read_only':
                    return error_response(403, "Insufficient permissions: Read-Write required")
                elif required_permission == 'full_access' and key_record.permissions not in ['full_access', 'read_write']:
                    return error_response(403, "Insufficient permissions: Full Access required")
                
                # Ejecutar la función original con la API Key
                result = f(*args, **kwargs, api_key=key_record)
                duration = (time.time() - start_time) * 1000
                
                # Log exitoso
                _logger.info(f"✅ Auth successful - Key: {key_record.name}, Duration: {duration:.2f}ms")
                
                return result
                
            except Exception as e:
                duration = (time.time() - start_time) * 1000
                _logger.error(f"❌ Auth error: {str(e)}", exc_info=True)
                return error_response(500, f"Authentication error: {str(e)}")
        
        return decorated_function
    return decorator

def error_response(status_code, message, details=None, api_key=None):
    """Respuesta de error estandarizada con registro de Log"""
    error_data = {
        'success': False,
        'error': {
            'code': status_code,
            'message': message,
            'timestamp': fields.Datetime.now().isoformat(),
        },
        'version': '1.0'
    }
    
    if details:
        error_data['error']['details'] = details

    # --- INSERCIÓN PARA LOGS ---
    if api_key:
        try:
            request.env['api.integration.log'].sudo().create({
                'name': f"API Error: {request.httprequest.path}",
                'api_key_id': api_key.id,
                'endpoint': request.httprequest.path,
                'method': request.httprequest.method,
                'status_code': str(status_code),
                'request_data': json.dumps(getattr(request, 'jsonrequest', {}) or request.httprequest.args.to_dict()),
                'response_data': json.dumps(error_data),
                'state': 'error',
                'error_message': message
            })
        except Exception as log_e:
            _logger.error(f"Error creating error log: {str(log_e)}")
    # ---------------------------
    
    return Response(
        json.dumps(error_data, indent=2),
        status=status_code,
        content_type='application/json'
    )

def success_response(data, message="Success", status_code=200, meta=None, api_key=None):
    """Respuesta exitosa estandarizada con registro de Log"""
    response_data = {
        'success': True,
        'data': data,
        'message': message,
        'version': '1.0',
        'timestamp': fields.Datetime.now().isoformat()
    }
    
    if meta:
        response_data['meta'] = meta

    # --- INSERCIÓN PARA LOGS ---
    if api_key:
        try:
            request.env['api.integration.log'].sudo().create({
                'name': f"API Call: {request.httprequest.path}",
                'api_key_id': api_key.id,
                'endpoint': request.httprequest.path,
                'method': request.httprequest.method,
                'status_code': str(status_code),
                'request_data': json.dumps(getattr(request, 'jsonrequest', {}) or request.httprequest.args.to_dict()),
                'response_data': json.dumps(response_data),
                'state': 'success',
                'execution_time': 0.0 # Opcional: calcular tiempo
            })
        except Exception as log_e:
            _logger.error(f"Error creating success log: {str(log_e)}")
    # ---------------------------
    
    return Response(
        json.dumps(response_data, indent=2),
        status=status_code,
        content_type='application/json'
    )

def validate_pagination_params(limit, offset):
    """Validar y ajustar parámetros de paginación"""
    try:
        limit = int(limit) if limit else 100
        offset = int(offset) if offset else 0
        
        if limit > 1000:
            limit = 1000
        if limit < 1:
            limit = 100
        if offset < 0:
            offset = 0
            
        return limit, offset
    except ValueError:
        return 100, 0

# ==============================================================================
# CONTROLADOR PRINCIPAL - VERSIÓN CORREGIDA
# ==============================================================================

class OdooIntegrationAPI(http.Controller):
    
    # ==================== ENDPOINTS DE DIAGNÓSTICO ====================
    
    @http.route('/api/v1/health', type='http', auth='none', methods=['GET'], csrf=False)
    def health_check(self):
        """Health Check - Verifica que el API esté funcionando"""
        try:
            health_info = {
                'status': 'healthy',
                'timestamp': fields.Datetime.now().isoformat(),
                'service': 'Odoo API Integration v2.0',
                'endpoints_available': 15
            }
            
            return success_response(health_info, "API is healthy and running")
            
        except Exception as e:
            _logger.error(f"Health check error: {str(e)}")
            return error_response(500, "Health check failed", str(e))
    
# ==================== ENDPOINTS DE DIAGNÓSTICO CORREGIDOS ====================
    
    @http.route('/api/v1/debug/keys', type='http', auth='none', methods=['GET'], csrf=False)
    def debug_api_keys(self):
        """Endpoint para debug - ver todas las API Keys en la BD"""
        try:
            # Forzar base de datos en Odoo 18 si auth='none'
            if not request.db:
                return error_response(500, "No database selected in request")
            
            # Buscamos las llaves usando sudo
            keys = request.env['api.integration.key'].sudo().search([])
            
            keys_data = []
            for key in keys:
                keys_data.append({
                    'id': key.id,
                    'name': key.name,
                    'key': key.key[:20] + '...' if key.key else 'None',
                    'active': key.active,
                    'company_name': key.company_id.name if key.company_id else 'No Company'
                })
            
            _logger.info(f"Debug Keys: Found {len(keys_data)} keys")
            
            # Retornamos éxito pasandole una key genérica si quieres que guarde Log, 
            # o dejarlo así para que solo responda.
            return success_response({
                'total_keys': len(keys_data),
                'keys': keys_data,
                'database': request.db
            })
            
        except Exception as e:
            _logger.error(f"Debug error: {str(e)}", exc_info=True)
            return error_response(500, f"Debug error: {str(e)}")

    @http.route('/api/v1/debug/test-key/<string:api_key>', type='http', auth='none', methods=['GET'], csrf=False)
    def debug_test_key(self, api_key):
        """Testear una API Key específica y FORZAR un Log"""
        try:
            key_clean = api_key.strip()
            key_record = request.env['api.integration.key'].sudo().search([
                ('key', '=', key_clean)
            ], limit=1)
            
            if key_record:
                # --- AQUÍ FORZAMOS EL LOG PARA QUE LO VEAS ---
                request.env['api.integration.log'].sudo().create({
                    'name': f"Manual Debug Check: {key_record.name}",
                    'api_key_id': key_record.id,
                    'endpoint': request.httprequest.path,
                    'method': 'GET',
                    'status_code': '200',
                    'state': 'success'
                })
                
                return success_response({
                    'found': True,
                    'name': key_record.name,
                    'active': key_record.active
                }, "API Key found and Log created")
            else:
                return error_response(404, "API Key not found in DB")
                
        except Exception as e:
            return error_response(500, str(e))
    
    @http.route('/api/v1/version', type='http', auth='none', methods=['GET'], csrf=False)
    def get_version(self):
        """Obtener información de versión"""
        version_info = {
            'api_version': '2.0',
            'odoo_version': '18.0',
            'module_version': '18.0.1.0.0',
            'timestamp': fields.Datetime.now().isoformat(),
            'status': 'active'
        }
        
        return success_response(version_info)
    
    # ==================== ENDPOINT DE PRUEBA DE AUTENTICACIÓN ====================
    
    @http.route('/api/v1/test/auth', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def test_auth(self, api_key=None):
        """Endpoint de prueba para verificar autenticación"""
        try:
            test_data = {
                'authenticated': True,
                'api_key_id': api_key.id,
                'api_key_name': api_key.name,
                'company_id': api_key.company_id.id if api_key.company_id else None,
                'company_name': api_key.company_id.name if api_key.company_id else '',
                'permissions': api_key.permissions,
                'timestamp': fields.Datetime.now().isoformat(),
                'message': '🎉 Authentication successful! API is working correctly.'
            }
            
            return success_response(test_data, "✅ Authentication successful")
            
        except Exception as e:
            _logger.error(f"Test auth error: {str(e)}", exc_info=True)
            return error_response(500, "Test authentication failed", str(e))
    
    # ==================== ENDPOINTS PRINCIPALES ====================
    @http.route('/api/v1/products/available', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_available_products(self, api_key=None, **kwargs):
        """Obtener productos disponibles con stock y datos de eCommerce (Odoo 18)"""
        try:
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = [('sale_ok', '=', True), ('active', '=', True)]
            
            # Contexto de compañía para Odoo 18
            company = api_key.company_id if api_key.company_id else request.env.company
            product_model = request.env['product.product'].sudo().with_company(company)
            
            # Filtros dinámicos
            category_id = request.httprequest.args.get('category_id')
            if category_id and category_id.isdigit():
                domain.append(('categ_id', '=', int(category_id)))
            
            search_term = request.httprequest.args.get('search')
            if search_term:
                domain.append('|')
                domain.append(('name', 'ilike', search_term))
                domain.append(('default_code', 'ilike', search_term))
            
            products = product_model.search(domain, limit=limit, offset=offset, order='name')
            
            product_data = []
            for product in products:
                # Accedemos al template para los campos de eCommerce
                template = product.product_tmpl_id
                
                product_data.append({
                    'id': product.id,
                    'name': product.name,
                    'default_code': product.default_code or '',
                    'list_price': product.list_price,
                    'qty_available': float(product.qty_available),
                    'categ_id': product.categ_id.id if product.categ_id else None,
                    'categ_name': product.categ_id.name if product.categ_id else '',
                    # --- NUEVOS CAMPOS SOLICITADOS ---
                    'description_ecommerce': template.description_ecommerce or '',
                    'website_url': template.website_url or '',
                    # ---------------------------------
                    'uom_id': product.uom_id.id if product.uom_id else None,
                    'uom_name': product.uom_id.name if product.uom_id else ''
                })
            
            total_count = product_model.search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(product_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(product_data)) < total_count
                }
            }
            
            return success_response({'products': product_data}, "Products retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_available_products: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching products", str(e))
    @http.route('/api/v1/orders/create', type='json', auth='none', methods=['POST'], csrf=False)
    @api_auth('read_write')
    def create_sale_order(self, **kwargs):
        """Crear un pedido de venta desde API"""
        try:
            order_data = request.jsonrequest
            api_key = kwargs.get('api_key')
            
            if not order_data.get('partner_id'):
                return error_response(400, "Partner ID is required")
            
            if not order_data.get('order_lines') or not isinstance(order_data['order_lines'], list):
                return error_response(400, "Order lines are required and must be a list")
            
            try:
                order = request.env['sale.order'].sudo().create_from_api(order_data, api_key)
            except Exception as e:
                return error_response(400, str(e))
            
            order_info = {
                'order_id': order.id,
                'order_name': order.name,
                'state': order.state,
                'amount_total': float(order.amount_total),
                'partner_id': order.partner_id.id,
                'partner_name': order.partner_id.name,
                'date_order': order.date_order.isoformat() if order.date_order else None
            }
            
            return success_response(order_info, "Order created successfully", 201)
            
        except Exception as e:
            _logger.error(f"Error in create_sale_order: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while creating order", str(e))
    
    @http.route('/api/v1/partners', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_partners(self, **kwargs):
        """Obtener lista de partners"""
        try:
            api_key = kwargs.get('api_key')
            
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = [('active', '=', True)]
            
            partner_type = request.httprequest.args.get('type')
            if partner_type == 'customer':
                domain.append(('customer_rank', '>', 0))
            elif partner_type == 'supplier':
                domain.append(('supplier_rank', '>', 0))
            
            search_term = request.httprequest.args.get('search')
            if search_term:
                domain.append(('name', 'ilike', search_term))
            
            partners = request.env['res.partner'].sudo().search(
                domain, 
                limit=limit, 
                offset=offset,
                order='name'
            )
            
            partner_data = []
            for partner in partners:
                partner_data.append({
                    'id': partner.id,
                    'name': partner.name,
                    'email': partner.email or '',
                    'phone': partner.phone or '',
                    'customer_rank': partner.customer_rank,
                    'supplier_rank': partner.supplier_rank,
                    'is_company': partner.is_company,
                    'street': partner.street or '',
                    'city': partner.city or '',
                    'country_id': partner.country_id.id if partner.country_id else None,
                    'country_name': partner.country_id.name if partner.country_id else ''
                })
            
            total_count = request.env['res.partner'].sudo().search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(partner_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(partner_data)) < total_count
                }
            }
            
            return success_response({'partners': partner_data}, "Partners retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_partners: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching partners", str(e))
    
    @http.route('/api/v1/categories', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_categories(self, **kwargs):
        """Obtener categorías de productos - CORREGIDO"""
        try:
            # ELIMINADO: ('active', '=', True) ya que product.category NO posee ese campo
            categories = request.env['product.category'].sudo().search([], order='name')
            
            category_data = []
            for category in categories:
                category_data.append({
                    'id': category.id,
                    'name': category.name,
                    'parent_id': category.parent_id.id if category.parent_id else None,
                    'parent_name': category.parent_id.name if category.parent_id else '',
                    'child_count': len(category.child_id)
                })
            
            return success_response({
                'categories': category_data,
                'total_count': len(category_data)
            }, "Categories retrieved successfully")
            
        except Exception as e:
            _logger.error(f"Error in get_categories: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching categories", str(e))
    
    @http.route('/api/v1/company/info', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_company_info(self, **kwargs):
        """Obtener información de la compañía"""
        try:
            api_key = kwargs.get('api_key')
            company = api_key.company_id
            
            company_info = {
                'id': company.id,
                'name': company.name,
                'street': company.street or '',
                'city': company.city or '',
                'country_id': company.country_id.id if company.country_id else None,
                'country_name': company.country_id.name if company.country_id else '',
                'phone': company.phone or '',
                'email': company.email or '',
                'website': company.website or '',
                'currency_id': company.currency_id.id,
                'currency_name': company.currency_id.name,
                'currency_symbol': company.currency_id.symbol,
                'vat': company.vat or ''
            }
            
            return success_response({'company': company_info}, "Company info retrieved successfully")
            
        except Exception as e:
            _logger.error(f"Error in get_company_info: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching company info", str(e))
    # ==============================================================================
    # ENDPOINT PARA REGISTRO DESDE WHATSAPP (BOT)
    # ==============================================================================

    @http.route('/api/v1/crm/leads/create', type='json', auth='none', methods=['POST'], csrf=False)
    @api_auth('read_write')
    def create_crm_lead_from_bot(self, **kwargs):
        api_key = kwargs.get('api_key')
        try:
            data = request.params
            user_api = api_key.user_id.sudo()

            # 1. Gestionar la Etiqueta 'API'
            # Buscamos la etiqueta por nombre para obtener su ID
            tag_name = "API"
            tag = request.env['crm.tag'].sudo().search([('name', '=', tag_name)], limit=1)
            if not tag:
                tag = request.env['crm.tag'].sudo().create({'name': tag_name, 'color': 3}) # Color 3 es verde

            lead_vals = {
                'name': data.get('name'),
                'contact_name': data.get('contact_name'),
                'email_from': data.get('email_from'),
                'phone': data.get('phone'),
                'description': data.get('description', 'Registrado vía API WhatsApp'),
                
                # LA CLAVE PARA EL EMBUDO:
                'type': 'opportunity',  # Esto lo pone en el Pipeline
                'priority': '2',        # 2 estrella
                'tag_ids': [(4, tag.id)], # (4, id) añade la etiqueta sin borrar otras
                
                'company_id': api_key.company_id.id,
                'user_id': user_api.id,
            }

            # 2. Crear el registro en la etapa 'Nuevo' (Stage_id se asigna solo al ser Nuevo)
            new_lead = request.env['crm.lead'].sudo().with_company(api_key.company_id.id).with_user(user_api).create(lead_vals)

            return {
                "success": True,
                "lead_id": new_lead.id,
                "message": f"Oportunidad '{lead_vals['name']}' creada con éxito en el embudo."
            }

        except Exception as e:
            _logger.error(f"❌ Error API CRM: {str(e)}")
            return {"success": False, "error": str(e)}
    # ==================== NUEVOS ENDPOINTS PARA MÚLTIPLES MÓDULOS ====================
    
    @http.route('/api/v1/contacts/detailed', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_detailed_contacts(self, **kwargs):
        """Obtener contactos detallados"""
        try:
            api_key = kwargs.get('api_key')
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = [('active', '=', True)]
            
            contact_type = request.httprequest.args.get('type')
            if contact_type == 'customer':
                domain.append(('customer_rank', '>', 0))
            elif contact_type == 'supplier':
                domain.append(('supplier_rank', '>', 0))
            elif contact_type == 'person':
                domain.append(('is_company', '=', False))
            elif contact_type == 'company':
                domain.append(('is_company', '=', True))
            
            search_term = request.httprequest.args.get('search')
            if search_term:
                domain.append(('name', 'ilike', search_term))
            
            partners = request.env['res.partner'].sudo().search(
                domain, limit=limit, offset=offset, order='name'
            )
            
            contact_data = []
            for partner in partners:
                contact_data.append({
                    'id': partner.id,
                    'name': partner.name,
                    'email': partner.email or '',
                    'phone': partner.phone or '',
                    'mobile': partner.mobile or '',
                    'is_company': partner.is_company,
                    'customer_rank': partner.customer_rank,
                    'supplier_rank': partner.supplier_rank,
                    'street': partner.street or '',
                    'city': partner.city or '',
                    'country_id': partner.country_id.id if partner.country_id else None,
                    'country_name': partner.country_id.name if partner.country_id else '',
                    'zip': partner.zip or '',
                    'website': partner.website or '',
                    'lang': partner.lang or '',
                    'create_date': partner.create_date.isoformat() if partner.create_date else None
                })
            
            total_count = request.env['res.partner'].sudo().search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(contact_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(contact_data)) < total_count
                }
            }
            
            return success_response({'contacts': contact_data}, "Contacts retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_detailed_contacts: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching contacts", str(e))
    
    @http.route('/api/v1/sales/orders', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_sales_orders(self, **kwargs):
        """Obtener órdenes de venta"""
        try:
            api_key = kwargs.get('api_key')
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = []
            
            state = request.httprequest.args.get('state')
            if state:
                domain.append(('state', '=', state))
            
            date_from = request.httprequest.args.get('date_from')
            if date_from:
                domain.append(('date_order', '>=', date_from))
            
            date_to = request.httprequest.args.get('date_to')
            if date_to:
                domain.append(('date_order', '<=', date_to))
            
            partner_id = request.httprequest.args.get('partner_id')
            if partner_id and partner_id.isdigit():
                domain.append(('partner_id', '=', int(partner_id)))
            
            orders = request.env['sale.order'].sudo().search(
                domain, limit=limit, offset=offset, order='date_order desc'
            )
            
            order_data = []
            for order in orders:
                order_data.append({
                    'id': order.id,
                    'name': order.name,
                    'partner_id': order.partner_id.id,
                    'partner_name': order.partner_id.name,
                    'date_order': order.date_order.isoformat() if order.date_order else None,
                    'state': order.state,
                    'amount_total': order.amount_total,
                    'amount_untaxed': order.amount_untaxed,
                    'amount_tax': order.amount_tax,
                    'currency_id': order.currency_id.id,
                    'currency_name': order.currency_id.name,
                    'user_id': order.user_id.id if order.user_id else None,
                    'user_name': order.user_id.name if order.user_id else '',
                    'team_id': order.team_id.id if order.team_id else None,
                    'team_name': order.team_id.name if order.team_id else '',
                    'order_lines_count': len(order.order_line),
                    'invoice_status': order.invoice_status,
                    'delivery_status': order.delivery_status
                })
            
            total_count = request.env['sale.order'].sudo().search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(order_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(order_data)) < total_count
                }
            }
            
            return success_response({'orders': order_data}, "Sales orders retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_sales_orders: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching sales orders", str(e))
    
    @http.route('/api/v1/sales/order-lines', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_sales_order_lines(self, **kwargs):
        """Obtener líneas de órdenes de venta"""
        try:
            api_key = kwargs.get('api_key')
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = []
            
            order_id = request.httprequest.args.get('order_id')
            if order_id and order_id.isdigit():
                domain.append(('order_id', '=', int(order_id)))
            
            product_id = request.httprequest.args.get('product_id')
            if product_id and product_id.isdigit():
                domain.append(('product_id', '=', int(product_id)))
            
            order_lines = request.env['sale.order.line'].sudo().search(
                domain, limit=limit, offset=offset, order='order_id, sequence'
            )
            
            line_data = []
            for line in order_lines:
                line_data.append({
                    'id': line.id,
                    'order_id': line.order_id.id,
                    'order_name': line.order_id.name,
                    'product_id': line.product_id.id,
                    'product_name': line.product_id.name,
                    'product_uom_qty': float(line.product_uom_qty),
                    'qty_delivered': float(line.qty_delivered),
                    'qty_invoiced': float(line.qty_invoiced),
                    'price_unit': float(line.price_unit),
                    'price_subtotal': float(line.price_subtotal),
                    'price_total': float(line.price_total),
                    'discount': float(line.discount),
                    'tax_id': [tax.id for tax in line.tax_id],
                    'tax_names': [tax.name for tax in line.tax_id],
                    'sequence': line.sequence,
                    'state': line.state,
                })
            
            total_count = request.env['sale.order.line'].sudo().search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(line_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(line_data)) < total_count
                }
            }
            
            return success_response({'order_lines': line_data}, "Order lines retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_sales_order_lines: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching order lines", str(e))
    
    @http.route('/api/v1/purchases/orders', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_purchase_orders(self, **kwargs):
        """Obtener órdenes de compra"""
        try:
            api_key = kwargs.get('api_key')
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = []
            
            state = request.httprequest.args.get('state')
            if state:
                domain.append(('state', '=', state))
            
            partner_id = request.httprequest.args.get('partner_id')
            if partner_id and partner_id.isdigit():
                domain.append(('partner_id', '=', int(partner_id)))
            
            orders = request.env['purchase.order'].sudo().search(
                domain, limit=limit, offset=offset, order='date_order desc'
            )
            
            order_data = []
            for order in orders:
                order_data.append({
                    'id': order.id,
                    'name': order.name,
                    'partner_id': order.partner_id.id,
                    'partner_name': order.partner_id.name,
                    'date_order': order.date_order.isoformat() if order.date_order else None,
                    'date_planned': order.date_planned.isoformat() if order.date_planned else None,
                    'state': order.state,
                    'amount_untaxed': float(order.amount_untaxed),
                    'amount_tax': float(order.amount_tax),
                    'amount_total': float(order.amount_total),
                    'currency_id': order.currency_id.id,
                    'user_id': order.user_id.id if order.user_id else None,
                    'incoterm_id': order.incoterm_id.id if order.incoterm_id else None,
                    'incoterm_name': order.incoterm_id.name if order.incoterm_id else '',
                    'order_lines_count': len(order.order_line),
                    'receipt_status': order.receipt_status,
                    'invoice_status': order.invoice_status,
                })
            
            total_count = request.env['purchase.order'].sudo().search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(order_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(order_data)) < total_count
                }
            }
            
            return success_response({'purchase_orders': order_data}, "Purchase orders retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_purchase_orders: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching purchase orders", str(e))
    
    @http.route('/api/v1/inventory/stock', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_inventory_stock(self, **kwargs):
        """Obtener información de stock"""
        try:
            api_key = kwargs.get('api_key')
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = []
            
            location_id = request.httprequest.args.get('location_id')
            if location_id and location_id.isdigit():
                domain.append(('location_id', '=', int(location_id)))
            
            product_id = request.httprequest.args.get('product_id')
            if product_id and product_id.isdigit():
                domain.append(('product_id', '=', int(product_id)))
            
            quants = request.env['stock.quant'].sudo().search(
                domain, limit=limit, offset=offset
            )
            
            stock_data = []
            for quant in quants:
                stock_data.append({
                    'id': quant.id,
                    'product_id': quant.product_id.id,
                    'product_name': quant.product_id.name,
                    'product_code': quant.product_id.default_code or '',
                    'location_id': quant.location_id.id,
                    'location_name': quant.location_id.name,
                    'quantity': float(quant.quantity),
                    'reserved_quantity': float(quant.reserved_quantity),
                    'available_quantity': float(quant.available_quantity),
                    'in_date': quant.in_date.isoformat() if quant.in_date else None,
                    'lot_id': quant.lot_id.id if quant.lot_id else None,
                    'lot_name': quant.lot_id.name if quant.lot_id else '',
                    'package_id': quant.package_id.id if quant.package_id else None,
                    'owner_id': quant.owner_id.id if quant.owner_id else None,
                })
            
            total_count = request.env['stock.quant'].sudo().search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(stock_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(stock_data)) < total_count
                }
            }
            
            return success_response({'inventory': stock_data}, "Inventory stock retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_inventory_stock: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching inventory", str(e))
    
    @http.route('/api/v1/accounting/invoices', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_accounting_invoices(self, **kwargs):
        """Obtener facturas contables"""
        try:
            api_key = kwargs.get('api_key')
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = [
                ('move_type', 'in', ['out_invoice', 'out_refund', 'in_invoice', 'in_refund'])
            ]
            
            move_type = request.httprequest.args.get('move_type')
            if move_type:
                domain.append(('move_type', '=', move_type))
            
            state = request.httprequest.args.get('state')
            if state:
                domain.append(('state', '=', state))
            
            partner_id = request.httprequest.args.get('partner_id')
            if partner_id and partner_id.isdigit():
                domain.append(('partner_id', '=', int(partner_id)))
            
            date_from = request.httprequest.args.get('date_from')
            if date_from:
                domain.append(('invoice_date', '>=', date_from))
            
            date_to = request.httprequest.args.get('date_to')
            if date_to:
                domain.append(('invoice_date', '<=', date_to))
            
            invoices = request.env['account.move'].sudo().search(
                domain, limit=limit, offset=offset, order='invoice_date desc, name desc'
            )
            
            invoice_data = []
            for invoice in invoices:
                invoice_data.append({
                    'id': invoice.id,
                    'name': invoice.name,
                    'partner_id': invoice.partner_id.id,
                    'partner_name': invoice.partner_id.name,
                    'move_type': invoice.move_type,
                    'state': invoice.state,
                    'invoice_date': invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                    'invoice_date_due': invoice.invoice_date_due.isoformat() if invoice.invoice_date_due else None,
                    'amount_untaxed': float(invoice.amount_untaxed),
                    'amount_tax': float(invoice.amount_tax),
                    'amount_total': float(invoice.amount_total),
                    'amount_residual': float(invoice.amount_residual),
                    'currency_id': invoice.currency_id.id,
                    'currency_name': invoice.currency_id.name,
                    'journal_id': invoice.journal_id.id,
                    'journal_name': invoice.journal_id.name,
                    'payment_state': invoice.payment_state,
                    'invoice_line_ids': [line.id for line in invoice.invoice_line_ids],
                })
            
            total_count = request.env['account.move'].sudo().search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(invoice_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(invoice_data)) < total_count
                }
            }
            
            return success_response({'invoices': invoice_data}, "Invoices retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_accounting_invoices: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching invoices", str(e))
    
    @http.route('/api/v1/crm/leads', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_crm_leads(self, **kwargs):
        """Obtener oportunidades/leads de CRM"""
        try:
            api_key = kwargs.get('api_key')
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = []
            
            stage_id = request.httprequest.args.get('stage_id')
            if stage_id and stage_id.isdigit():
                domain.append(('stage_id', '=', int(stage_id)))
            
            user_id = request.httprequest.args.get('user_id')
            if user_id and user_id.isdigit():
                domain.append(('user_id', '=', int(user_id)))
            
            type_filter = request.httprequest.args.get('type')
            if type_filter:
                domain.append(('type', '=', type_filter))
            
            leads = request.env['crm.lead'].sudo().search(
                domain, limit=limit, offset=offset, order='create_date desc'
            )
            
            lead_data = []
            for lead in leads:
                lead_data.append({
                    'id': lead.id,
                    'name': lead.name,
                    'partner_id': lead.partner_id.id if lead.partner_id else None,
                    'partner_name': lead.partner_id.name if lead.partner_id else '',
                    'type': lead.type,
                    'stage_id': lead.stage_id.id,
                    'stage_name': lead.stage_id.name,
                    'user_id': lead.user_id.id if lead.user_id else None,
                    'user_name': lead.user_id.name if lead.user_id else '',
                    'team_id': lead.team_id.id if lead.team_id else None,
                    'team_name': lead.team_id.name if lead.team_id else '',
                    'email_from': lead.email_from or '',
                    'phone': lead.phone or '',
                    'probability': float(lead.probability),
                    'expected_revenue': float(lead.expected_revenue),
                    'priority': lead.priority,
                })
            
            total_count = request.env['crm.lead'].sudo().search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(lead_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(lead_data)) < total_count
                }
            }
            
            return success_response({'leads': lead_data}, "CRM leads retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_crm_leads: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching CRM leads", str(e))
    
    @http.route('/api/v1/hr/employees', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_employees(self, **kwargs):
        """Obtener información de empleados"""
        try:
            api_key = kwargs.get('api_key')
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = [('active', '=', True)]
            
            department_id = request.httprequest.args.get('department_id')
            if department_id and department_id.isdigit():
                domain.append(('department_id', '=', int(department_id)))
            
            job_id = request.httprequest.args.get('job_id')
            if job_id and job_id.isdigit():
                domain.append(('job_id', '=', int(job_id)))
            
            employees = request.env['hr.employee'].sudo().search(
                domain, limit=limit, offset=offset, order='name'
            )
            
            employee_data = []
            for employee in employees:
                employee_data.append({
                    'id': employee.id,
                    'name': employee.name,
                    'work_email': employee.work_email or '',
                    'work_phone': employee.work_phone or '',
                    'department_id': employee.department_id.id if employee.department_id else None,
                    'department_name': employee.department_id.name if employee.department_id else '',
                    'job_id': employee.job_id.id if employee.job_id else None,
                    'job_title': employee.job_id.name if employee.job_id else '',
                    'parent_id': employee.parent_id.id if employee.parent_id else None,
                    'manager_name': employee.parent_id.name if employee.parent_id else '',
                    'coach_id': employee.coach_id.id if employee.coach_id else None,
                    'coach_name': employee.coach_id.name if employee.coach_id else '',
                    'address_id': employee.address_id.id if employee.address_id else None,
                    'work_location': employee.work_location or '',
                })
            
            total_count = request.env['hr.employee'].sudo().search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(employee_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(employee_data)) < total_count
                }
            }
            
            return success_response({'employees': employee_data}, "Employees retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_employees: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching employees", str(e))
    
    @http.route('/api/v1/products/detailed', type='http', auth='none', methods=['GET'], csrf=False)
    @api_auth('read_only')
    def get_detailed_products(self, **kwargs):
        """Obtener productos con información detallada"""
        try:
            api_key = kwargs.get('api_key')
            limit, offset = validate_pagination_params(
                request.httprequest.args.get('limit'),
                request.httprequest.args.get('offset')
            )
            
            domain = []
            
            category_id = request.httprequest.args.get('category_id')
            if category_id and category_id.isdigit():
                domain.append(('categ_id', '=', int(category_id)))
            
            search_term = request.httprequest.args.get('search')
            if search_term:
                domain.append('|')
                domain.append(('name', 'ilike', search_term))
                domain.append(('default_code', 'ilike', search_term))
            
            products = request.env['product.product'].sudo().search(
                domain, limit=limit, offset=offset, order='name'
            )
            
            product_data = []
            for product in products:
                product_data.append({
                    'id': product.id,
                    'name': product.name,
                    'default_code': product.default_code or '',
                    'barcode': product.barcode or '',
                    'categ_id': product.categ_id.id,
                    'category_name': product.categ_id.name,
                    'list_price': float(product.list_price),
                    'standard_price': float(product.standard_price),
                    'qty_available': float(product.qty_available),
                    'virtual_available': float(product.virtual_available),
                    'incoming_qty': float(product.incoming_qty),
                    'outgoing_qty': float(product.outgoing_qty),
                    'uom_id': product.uom_id.id,
                    'uom_name': product.uom_id.name,
                    'description': product.description or '',
                    'description_sale': product.description_sale or '',
                    'type': product.type,
                    'sale_ok': product.sale_ok,
                    'purchase_ok': product.purchase_ok,
                    'active': product.active,
                    'weight': float(product.weight) if product.weight else 0.0,
                    'volume': float(product.volume) if product.volume else 0.0,
                    'create_date': product.create_date.isoformat() if product.create_date else None,
                    'write_date': product.write_date.isoformat() if product.write_date else None,
                })
            
            total_count = request.env['product.product'].sudo().search_count(domain)
            
            meta = {
                'pagination': {
                    'total': total_count,
                    'count': len(product_data),
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + len(product_data)) < total_count
                }
            }
            
            return success_response({'products': product_data}, "Detailed products retrieved successfully", meta=meta)
            
        except Exception as e:
            _logger.error(f"Error in get_detailed_products: {str(e)}", exc_info=True)
            return error_response(500, "Internal server error while fetching detailed products", str(e))
