{
    'name': 'Interconectados SMS Marketing',
    'version': '18.0.3.0.0',
    'summary': 'SMS Marketing completo via Interconectados.net para Venezuela',
    'description': """
        Modulo completo de SMS Marketing integrado con Interconectados.net:
        - Envio de SMS individual y masivo
        - Carga de numeros desde archivo CSV/Excel
        - Plantillas de SMS reutilizables
        - Mensajes automaticos programados (cron)
        - Envio desde ficha de Contacto
        - Envio desde Facturas
        - Historial completo de envios
        - Gestion de credenciales segura y permanente
    """,
    'author': 'Alexander Sanchez Kode_IA',
    'category': 'Marketing',
    'depends': ['base', 'mail', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'views/sms_template_views.xml',
        'views/sms_campaign_views.xml',
        'views/sms_history_views.xml',
        'views/res_partner_views.xml',
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/sms_composer_views.xml',
        'views/menu_views.xml',
        'data/sms_cron.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'price': 9.98,
    'currency': 'USD',
}
