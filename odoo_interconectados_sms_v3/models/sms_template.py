from odoo import models, fields, api


class SmsTemplate(models.Model):
    _name = 'interconectados.sms.template'
    _description = 'Plantilla de SMS'
    _order = 'name'

    name = fields.Char(string="Nombre de la plantilla", required=True)
    body = fields.Text(
        string="Cuerpo del mensaje",
        required=True,
        help="Puedes usar variables dinamicas: {nombre}, {empresa}, {telefono}, {fecha}",
    )
    model_id = fields.Many2one(
        'ir.model',
        string="Aplica para",
        help="Modelo de Odoo al que aplica esta plantilla (Contacto, Factura, etc.)",
        ondelete='set null',
    )
    active = fields.Boolean(default=True)
    char_count = fields.Integer(
        string="Caracteres",
        compute='_compute_char_count',
        store=True,
    )
    sms_count = fields.Integer(
        string="SMS necesarios",
        compute='_compute_char_count',
        store=True,
    )
    campaign_count = fields.Integer(
        string="Campanas",
        compute='_compute_campaign_count',
    )

    @api.depends('body')
    def _compute_char_count(self):
        for rec in self:
            length = len(rec.body or '')
            rec.char_count = length
            if length == 0:
                rec.sms_count = 0
            elif length <= 160:
                rec.sms_count = 1
            elif length <= 305:
                rec.sms_count = 2
            elif length <= 457:
                rec.sms_count = 3
            elif length <= 609:
                rec.sms_count = 4
            else:
                rec.sms_count = 5

    def _compute_campaign_count(self):
        for rec in self:
            rec.campaign_count = self.env['interconectados.sms.campaign'].search_count(
                [('template_id', '=', rec.id)]
            )

    def render_body(self, record=None, extra_vars=None):
        """Renderiza el cuerpo reemplazando variables dinamicas."""
        body = self.body or ''
        variables = {}
        if record:
            if hasattr(record, 'name') and record.name:
                variables['nombre'] = record.name
            if hasattr(record, 'company_name') and record.company_name:
                variables['empresa'] = record.company_name
            elif hasattr(record, 'company_id') and record.company_id:
                variables['empresa'] = record.company_id.name
            if hasattr(record, 'phone') and record.phone:
                variables['telefono'] = record.phone
            if hasattr(record, 'mobile') and record.mobile:
                variables['movil'] = record.mobile
            if hasattr(record, 'amount_total'):
                variables['monto'] = str(record.amount_total)
            if hasattr(record, 'name') and 'INV' in str(record.name or ''):
                variables['factura'] = record.name
        if extra_vars:
            variables.update(extra_vars)
        from datetime import date
        variables['fecha'] = date.today().strftime('%d/%m/%Y')
        for key, val in variables.items():
            body = body.replace('{' + key + '}', str(val))
        return body
