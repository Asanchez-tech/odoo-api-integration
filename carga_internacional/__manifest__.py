{
    'name': 'Carga Internacional',
    'version': '18.0.6.0.3',
    'category': 'Inventory/Logistics',
    'summary': 'Importaciones: conteo previo a recepción, auditoría y multi-empresa',
    'description': (
        'Gestión de cargas internacionales. '
        'Flujo: Preparando → En Camino → En Conteo → Recibido. '
        'Muestra productos serializables como información. '
        'Los seriales se gestionan directamente en el WH/IN de Odoo.'
    ),
    'author': 'Alexander Sanchez Kode_IA',
    'depends': ['purchase', 'stock', 'mail', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'views/ir_sequence_data.xml',
        'views/carga_view_form.xml',
        'views/carga_view_list.xml',
        'views/wizard_excepcion_view.xml',
        'views/menu_view.xml',
        'report/report_conteo.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'price': 30.99,
    'currency': 'USD',

}
