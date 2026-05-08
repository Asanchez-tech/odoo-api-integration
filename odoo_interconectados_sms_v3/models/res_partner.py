from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    sms_history_ids = fields.One2many(
        'interconectados.sms.history', 'partner_id', string="SMS enviados"
    )
    sms_count = fields.Integer(
        string="SMS",
        compute='_compute_sms_count',
        store=True,
    )

    def _compute_sms_count(self):
        for rec in self:
            rec.sms_count = self.env['interconectados.sms.history'].search_count(
                [('partner_id', '=', rec.id)]
            )

    def _get_sms_phone(self):
        """Devuelve el mejor numero disponible para SMS (movil primero)."""
        return self.mobile or self.phone or ''

    def action_send_sms(self):
        """Abre el wizard usando el telefono fijo del contacto."""
        return self._open_sms_wizard(phone=self.phone or self.mobile or '')

    def action_send_sms_mobile(self):
        """Abre el wizard usando el movil del contacto."""
        return self._open_sms_wizard(phone=self.mobile or self.phone or '')

    def _open_sms_wizard(self, phone=''):
        return {
            'name': f"Enviar SMS a {self.name}",
            'type': 'ir.actions.act_window',
            'res_model': 'interconectados.sms.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_phone_numbers': phone,
                'default_partner_id': self.id,
            },
        }

    def action_view_sms_history(self):
        return {
            'name': f"SMS — {self.name}",
            'type': 'ir.actions.act_window',
            'res_model': 'interconectados.sms.history',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
