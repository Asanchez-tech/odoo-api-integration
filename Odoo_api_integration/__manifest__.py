{
    'name': 'API Integration for Odoo 18',
    'version': '18.0.1.0.0',
    'category': 'Tools',
    'summary': 'API for Odoo-to-Odoo integration with product sync and order management',
    'description': """
        Advanced API integration module for Odoo 18
        - Secure API key authentication
        - Multi-company support
        - Product catalog synchronization
        - Cross-Odoo order creation
        - Comprehensive logging and security
    """,
    'author': 'Alexander Sanchez Kode_IA',
    'website': 'https://www.kode-tech.com',
    'depends': [
        'base', 
        'sale', 
        'stock', 
        'product',
        'purchase',
        'account',
        'crm',
        'contacts',
        'hr'
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security_rules.xml',
        'views/api_keys_views.xml',
        'views/api_logs_views.xml',
    ],
    'demo': [],
    'images': [
        'static/description/icon.png',
        'static/description/screenshot_1.png',
        'static/description/screenshot_2.png',
        'static/description/screenshot_3.png',
        'static/description/screenshot_4.png',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'price': 9.98,
    'currency': 'USD',
}
