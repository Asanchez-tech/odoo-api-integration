from odoo import models, fields


class AccountMove(models.Model):
    _inherit = 'account.move'

    sms_history_ids = fields.One2many(
        'interconectados.sms.history', 'move_id', string="SMS enviados"
    )
    sms_count = fields.Integer(
        string="SMS", compute='_compute_sms_count'
    )

    def _compute_sms_count(self):
        for rec in self:
            rec.sms_count = len(rec.sms_history_ids)

    def action_send_sms(self):
        """Abre el wizard pre-cargado con el telefono del cliente de la factura."""
        partner = self.partner_id
        phone = ''
        if partner:
            phone = partner.mobile or partner.phone or ''
        return {
            'name': f"Enviar SMS — {self.name}",
            'type': 'ir.actions.act_window',
            'res_model': 'interconectados.sms.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_phone_numbers': phone,
                'default_partner_id': partner.id if partner else False,
                'default_move_id': self.id,
                'default_template_context': 'invoice',
            },
        }

    def action_view_sms_history(self):
        return {
            'name': f"SMS — {self.name}",
            'type': 'ir.actions.act_window',
            'res_model': 'interconectados.sms.history',
            'view_mode': 'list,form',
            'domain': [('move_id', '=', self.id)],
        }
