from odoo import models, fields, api


class SmsHistory(models.Model):
    _name = 'interconectados.sms.history'
    _description = 'Historial de SMS enviados'
    _order = 'date_sent desc'

    date_sent = fields.Datetime(
        string="Fecha de envio",
        default=fields.Datetime.now,
        readonly=True,
    )
    phone = fields.Char(string="Telefono", readonly=True, index=True)
    message = fields.Text(string="Mensaje", readonly=True)
    state = fields.Selection([
        ('sent', 'Enviado'),
        ('error', 'Error'),
    ], string="Estado", default='sent', readonly=True)
    error_message = fields.Char(string="Detalle del error", readonly=True)
    campaign_id = fields.Many2one(
        'interconectados.sms.campaign',
        string="Campana",
        readonly=True,
        ondelete='set null',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Contacto",
        readonly=True,
        ondelete='set null',
        index=True,
    )
    move_id = fields.Many2one(
        'account.move',
        string="Factura",
        readonly=True,
        ondelete='set null',
    )
    response_code = fields.Char(string="Codigo API", readonly=True)

    @api.model
    def create(self, vals):
        """
        Al crear un registro de historial, si no viene partner_id
        busca automaticamente un contacto que tenga ese numero de telefono
        (campo mobile o phone) y lo vincula.
        """
        record = super().create(vals)
        if not record.partner_id and record.phone:
            partner = self.env['res.partner'].search([
                '|',
                ('mobile', '=', record.phone),
                ('phone', '=', record.phone),
            ], limit=1)
            if partner:
                record.partner_id = partner.id
        return record
