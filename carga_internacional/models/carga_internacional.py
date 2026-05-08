# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# MODELO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════
class CargaInternacional(models.Model):
    _name = 'carga.internacional'
    _description = 'Carga Internacional'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'fecha_salida desc, name desc'
    _check_company_auto = True

    # ── Identificación ────────────────────────────────────────────────────────
    name = fields.Char(string='Referencia', readonly=True, copy=False, default='Nuevo', tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Empresa', required=True, index=True,
        default=lambda self: self.env.company, tracking=True,
    )

    # ── Logística ─────────────────────────────────────────────────────────────
    proveedor_logistico_id = fields.Many2one(
        'res.partner', string='Proveedor Logístico', required=True,
        tracking=True, check_company=True,
    )
    tipo_transporte = fields.Selection(
        [('aereo', 'Aéreo'), ('maritimo', 'Marítimo')],
        string='Tipo de Transporte', required=True, tracking=True,
    )
    fecha_salida = fields.Date(string='Fecha de Salida', required=True, tracking=True)
    fecha_estimada_llegada = fields.Date(
        string='Fecha Estimada de Llegada',
        compute='_compute_fecha_estimada_llegada', store=True, tracking=True,
    )
    fecha_real_recepcion = fields.Date(string='Fecha Real de Recepción', tracking=True)
    dias_retraso = fields.Integer(
        string='Días de Retraso', compute='_compute_dias_retraso', store=True,
        help='Positivo = retraso, negativo = llegó antes.',
    )
    urgente = fields.Selection(
        [('0', 'Normal'), ('1', 'Urgente'), ('2', 'Muy Urgente'), ('3', 'Crítico')],
        string='Urgencia', default='0', tracking=True,
    )

    # ── Documental ────────────────────────────────────────────────────────────
    numero_factura_proveedor = fields.Char(string='Nro. Factura del Proveedor', tracking=True)
    numero_bl_awb = fields.Char(string='BL / AWB', tracking=True,
        help='Número de Bill of Lading (marítimo) o Air Waybill (aéreo).')
    puerto_origen = fields.Char(string='Puerto / Aeropuerto Origen', tracking=True)
    puerto_destino = fields.Char(string='Puerto / Aeropuerto Destino', tracking=True)
    incoterm_id = fields.Many2one('account.incoterms', string='Incoterm', tracking=True)
    peso_total = fields.Float(string='Peso Total (kg)', digits=(16, 3), tracking=True)
    volumen_total = fields.Float(string='Volumen Total (m³)', digits=(16, 3), tracking=True)
    notas = fields.Text(string='Notas Internas')

    # ── Estado ────────────────────────────────────────────────────────────────
    # Flujo: preparando → en_camino → en_conteo → recibido
    estado = fields.Selection(
        [('preparando', 'Preparando'), ('en_camino', 'En Camino'),
         ('en_conteo', 'En Conteo'), ('recibido', 'Recibido')],
        string='Estado', default='preparando', required=True, tracking=True,
    )
    estado_auditoria = fields.Selection(
        [('sin_auditar', 'Sin Auditar'), ('en_conteo', 'En Conteo'),
         ('descuadre', 'Descuadre Detectado'), ('segundo_conteo', 'Segundo Conteo'),
         ('excepcion', 'Excepción Aplicada'), ('auditado', 'Auditado')],
        string='Estado de Auditoría', default='sin_auditar', required=True, tracking=True,
    )

    # ── Relaciones ────────────────────────────────────────────────────────────
    purchase_order_ids = fields.Many2many(
        'purchase.order', 'carga_internacional_purchase_rel', 'carga_id', 'purchase_id',
        string='Órdenes de Compra',
        domain="[('state', 'in', ['purchase', 'done']), ('company_id', '=', company_id)]",
        tracking=True, check_company=True,
    )
    line_ids = fields.One2many('carga.internacional.line', 'carga_id', string='Líneas de Carga')
    incidencia_ids = fields.One2many('carga.internacional.incidencia', 'carga_id', string='Incidencias')
    product_ids = fields.Many2many(
        'product.product', string='Productos de la Carga',
        compute='_compute_product_ids',
    )

    # ── Recepciones vinculadas ─────────────────────────────────────────────────
    picking_ids = fields.Many2many(
        'stock.picking', 'carga_internacional_picking_rel', 'carga_id', 'picking_id',
        string='Recepciones de Inventario', copy=False,
    )
    picking_count = fields.Integer(string='Cant. Recepciones', compute='_compute_picking_count')
    picking_state = fields.Selection(
        [('sin_recepciones', 'Sin Recepciones'), ('pendiente', 'Pendiente'),
         ('parcial', 'Parcial'), ('completo', 'Completado')],
        string='Estado Recepciones', compute='_compute_picking_count', store=True,
    )

    # ── Info serializables (solo informativo) ──────────────────────────────────
    requiere_seriales = fields.Boolean(
        string='Tiene Productos Serializables',
        compute='_compute_requiere_seriales', store=True,
        help='Indica que hay productos con número de serie o lote. '
             'Los seriales se gestionan directamente en la recepción de inventario (WH/IN).',
    )

    # ── Conteo / Auditoría ─────────────────────────────────────────────────────
    conteo_realizado = fields.Boolean(string='Primer Conteo Realizado', default=False, tracking=True)
    segundo_conteo_realizado = fields.Boolean(string='Segundo Conteo Realizado', default=False, tracking=True)
    tiene_descuadre = fields.Boolean(string='Tiene Descuadre', compute='_compute_tiene_descuadre', store=True)
    excepcion_justificada = fields.Boolean(string='Excepción Justificada', default=False, tracking=True)
    excepcion_justificacion = fields.Text(string='Justificación de Excepción', tracking=True)
    excepcion_usuario_id = fields.Many2one('res.users', string='Excepción Autorizada por', readonly=True, tracking=True)
    excepcion_fecha = fields.Datetime(string='Fecha de Excepción', readonly=True)

    # ── Condición de la Mercancía ──────────────────────────────────────────────
    condicion_mercancia = fields.Selection(
        [('buena', 'Buena — Sin novedades'), ('cajas_danadas', 'Cajas Dañadas'),
         ('mercancia_danada', 'Mercancía Dañada'), ('faltante_parcial', 'Faltante Parcial'),
         ('sobrante', 'Sobrante'), ('mixta', 'Incidencia Mixta')],
        string='Condición de la Mercancía', tracking=True,
    )
    condicion_detalle = fields.Text(string='Detalle de Condición / Incidencias Generales', tracking=True)
    cantidad_cajas_total = fields.Integer(string='Cajas Esperadas', tracking=True)
    cantidad_cajas_recibidas = fields.Integer(string='Cajas Recibidas', tracking=True)
    cantidad_cajas_danadas = fields.Integer(string='Cajas Dañadas', tracking=True)
    foto_evidencia = fields.Binary(string='Foto de Evidencia', attachment=True)
    foto_evidencia_nombre = fields.Char(string='Nombre del Archivo')

    # ── Totales ───────────────────────────────────────────────────────────────
    total_cantidad = fields.Float(string='Cantidad Total Pedida', compute='_compute_totales', store=True)
    total_cantidad_recibida = fields.Float(string='Total Recibido (Conteo)', compute='_compute_totales', store=True)
    total_valoracion = fields.Monetary(
        string='Valoración Total', compute='_compute_totales', store=True, currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Moneda', related='company_id.currency_id', store=True, readonly=True,
    )
    auditado_por_id = fields.Many2one('res.users', string='Auditado por', readonly=True, tracking=True)
    fecha_auditoria = fields.Datetime(string='Fecha de Auditoría', readonly=True)

    # ════════════════════════════════════════════════════════════════════════
    # COMPUTES
    # ════════════════════════════════════════════════════════════════════════

    @api.depends('fecha_salida', 'tipo_transporte')
    def _compute_fecha_estimada_llegada(self):
        for rec in self:
            if rec.fecha_salida and rec.tipo_transporte:
                dias = 5 if rec.tipo_transporte == 'aereo' else 21
                rec.fecha_estimada_llegada = rec.fecha_salida + timedelta(days=dias)
            else:
                rec.fecha_estimada_llegada = False

    @api.depends('fecha_estimada_llegada', 'fecha_real_recepcion')
    def _compute_dias_retraso(self):
        for rec in self:
            if rec.fecha_estimada_llegada and rec.fecha_real_recepcion:
                rec.dias_retraso = (rec.fecha_real_recepcion - rec.fecha_estimada_llegada).days
            else:
                rec.dias_retraso = 0

    @api.depends('line_ids.cantidad', 'line_ids.subtotal', 'line_ids.cantidad_recibida')
    def _compute_totales(self):
        for rec in self:
            rec.total_cantidad = sum(rec.line_ids.mapped('cantidad'))
            rec.total_cantidad_recibida = sum(rec.line_ids.mapped('cantidad_recibida'))
            rec.total_valoracion = sum(rec.line_ids.mapped('subtotal'))

    @api.depends('line_ids.tiene_descuadre')
    def _compute_tiene_descuadre(self):
        for rec in self:
            rec.tiene_descuadre = any(rec.line_ids.mapped('tiene_descuadre'))

    @api.depends('line_ids.product_id', 'line_ids.tracking')
    def _compute_requiere_seriales(self):
        for rec in self:
            rec.requiere_seriales = any(
                l.tracking in ('serial', 'lot') for l in rec.line_ids if l.product_id
            )

    @api.depends('line_ids.product_id')
    def _compute_product_ids(self):
        for rec in self:
            rec.product_ids = rec.line_ids.mapped('product_id')

    @api.depends('picking_ids', 'picking_ids.state')
    def _compute_picking_count(self):
        for rec in self:
            pickings = rec.picking_ids
            rec.picking_count = len(pickings)
            if not pickings:
                rec.picking_state = 'sin_recepciones'
            elif all(p.state == 'done' for p in pickings):
                rec.picking_state = 'completo'
            elif any(p.state == 'done' for p in pickings):
                rec.picking_state = 'parcial'
            else:
                rec.picking_state = 'pendiente'

    # ════════════════════════════════════════════════════════════════════════
    # ORM
    # ════════════════════════════════════════════════════════════════════════

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nuevo') == 'Nuevo':
                company_id = vals.get('company_id', self.env.company.id)
                company = self.env['res.company'].browse(company_id)
                sequence = self.env['ir.sequence'].with_company(company).next_by_code(
                    'carga.internacional') or 'Nuevo'
                vals['name'] = sequence
        return super().create(vals_list)

    # ════════════════════════════════════════════════════════════════════════
    # ONCHANGE
    # ════════════════════════════════════════════════════════════════════════

    @api.onchange('company_id')
    def _onchange_company_id(self):
        self.purchase_order_ids = False
        self.line_ids = False
        self.picking_ids = False

    @api.onchange('purchase_order_ids')
    def _onchange_purchase_order_ids(self):
        self._sync_lines_from_po()
        self._adopt_existing_pickings()

    def _sync_lines_from_po(self):
        for rec in self:
            existing = {l.purchase_line_id.id: l for l in rec.line_ids if l.purchase_line_id}
            needed = set()
            new_lines = []
            for po in rec.purchase_order_ids:
                for pol in po.order_line:
                    needed.add(pol.id)
                    if pol.id not in existing:
                        new_lines.append((0, 0, {
                            'purchase_line_id': pol.id,
                            'product_id': pol.product_id.id,
                            'cantidad': pol.product_qty,
                            'costo_unitario': pol.price_unit,
                        }))
            remove_cmds = [
                (3, line.id) for line in rec.line_ids
                if line.purchase_line_id and line.purchase_line_id.id not in needed
            ]
            if remove_cmds or new_lines:
                rec.line_ids = remove_cmds + new_lines

    def _adopt_existing_pickings(self):
        """Vincula las recepciones ya generadas por Odoo al confirmar las OC (sin crear nuevas)."""
        for rec in self:
            if not rec.purchase_order_ids:
                rec.picking_ids = False
                return
            company_id = rec.company_id.id if rec.company_id else self.env.company.id
            pickings = self.env['stock.picking'].search([
                ('purchase_id', 'in', rec.purchase_order_ids.ids),
                ('picking_type_code', '=', 'incoming'),
                ('company_id', '=', company_id),
                ('state', 'not in', ['cancel']),
            ])
            rec.picking_ids = [(6, 0, pickings.ids)]

    # ════════════════════════════════════════════════════════════════════════
    # FLUJO PRINCIPAL
    # preparando → en_camino → en_conteo → recibido
    # ════════════════════════════════════════════════════════════════════════

    def action_en_camino(self):
        self._validar_transicion('preparando', 'en_camino')
        self._adopt_existing_pickings()
        self.write({'estado': 'en_camino'})
        self.message_post(
            body=_('Carga marcada como EN CAMINO. Recepciones vinculadas: %d.') % self.picking_count,
            subtype_xmlid='mail.mt_note',
        )

    def action_iniciar_conteo(self):
        """La carga llegó físicamente — se inicia el conteo antes de validar en inventario."""
        self._validar_transicion('en_camino', 'en_conteo')
        if not self.line_ids:
            raise UserError(_('No hay líneas de productos. Vincule las Órdenes de Compra primero.'))
        self._adopt_existing_pickings()
        self.write({'estado': 'en_conteo', 'estado_auditoria': 'en_conteo'})
        # Aviso informativo si hay productos serializables
        if self.requiere_seriales:
            prods = ', '.join(
                self.line_ids.filtered(lambda l: l.tracking in ('serial', 'lot'))
                .mapped('product_id.display_name')
            )
            self.message_post(
                body=_(
                    'Conteo iniciado por %s.<br/>'
                    '<b>⚠️ Productos con número de serie/lote:</b> %s<br/>'
                    'Los seriales se deben ingresar directamente en la recepción '
                    'de inventario (WH/IN) antes o después de validar.'
                ) % (self.env.user.name, prods),
                subtype_xmlid='mail.mt_note',
            )
        else:
            self.message_post(
                body=_('Conteo iniciado por %s.') % self.env.user.name,
                subtype_xmlid='mail.mt_note',
            )

    def action_recibido(self):
        """
        Cierre final: auditoría completa → valida la recepción en Odoo.
        Los seriales se gestionan en el WH/IN directamente.
        """
        self._validar_transicion('en_conteo', 'recibido')
        if self.estado_auditoria not in ('auditado', 'excepcion'):
            raise UserError(
                _('El conteo debe estar auditado antes de cerrar.\n'
                  'Estado actual de auditoría: %s') % dict(
                    self._fields['estado_auditoria'].selection).get(self.estado_auditoria, '')
            )
        self._adopt_existing_pickings()
        self.write({'estado': 'recibido', 'fecha_real_recepcion': fields.Date.today()})
        self._validar_recepciones()
        self.message_post(
            body=_('Carga marcada como RECIBIDA. Inventario actualizado.'),
            subtype_xmlid='mail.mt_note',
        )

    def action_preparando(self):
        for rec in self:
            if rec.estado == 'recibido':
                raise UserError(_('No se puede revertir una carga ya recibida.'))
        self.write({'estado': 'preparando'})

    def action_revertir_a_en_camino(self):
        for rec in self:
            if rec.estado != 'en_conteo':
                raise UserError(_('Solo se puede revertir desde el estado En Conteo.'))
        self.write({'estado': 'en_camino', 'estado_auditoria': 'sin_auditar'})

    def _validar_transicion(self, estado_origen, estado_destino):
        for rec in self:
            if rec.estado != estado_origen:
                raise UserError(
                    _('Solo se puede pasar a "%s" desde "%s".') % (estado_destino, estado_origen)
                )

    # ════════════════════════════════════════════════════════════════════════
    # FLUJO DE CONTEO Y AUDITORÍA
    # ════════════════════════════════════════════════════════════════════════

    def action_confirmar_primer_conteo(self):
        self.ensure_one()
        if self.estado != 'en_conteo':
            raise UserError(_('Solo se puede confirmar el conteo cuando la carga está En Conteo.'))
        if self.line_ids.filtered(lambda l: l.cantidad_recibida < 0):
            raise UserError(_('Hay líneas con cantidad negativa. Revise el conteo.'))
        lineas_no_contadas = self.line_ids.filtered(lambda l: not l.conteo_realizado)
        if lineas_no_contadas:
            raise UserError(
                _('Los siguientes productos no han sido contados:\n%s') %
                ', '.join(lineas_no_contadas.mapped('product_id.name'))
            )
        for line in self.line_ids:
            line._compute_descuadre()
        if self.tiene_descuadre:
            self.write({'estado_auditoria': 'descuadre', 'conteo_realizado': True})
            descuadres = self.line_ids.filtered('tiene_descuadre')
            detalle = '\n'.join([
                '• %s: pedido %.2f / recibido %.2f / diferencia %+.2f' % (
                    l.product_id.name, l.cantidad, l.cantidad_recibida, l.diferencia_conteo
                ) for l in descuadres
            ])
            self.message_post(
                body=_('DESCUADRE detectado.\n\n%s') % detalle,
                subtype_xmlid='mail.mt_note',
            )
        else:
            self.write({
                'estado_auditoria': 'auditado', 'conteo_realizado': True,
                'auditado_por_id': self.env.user.id, 'fecha_auditoria': fields.Datetime.now(),
            })
            self.message_post(
                body=_('Primer conteo SIN descuadres. Auditado por %s.') % self.env.user.name,
                subtype_xmlid='mail.mt_note',
            )

    def action_solicitar_segundo_conteo(self):
        self.ensure_one()
        if self.estado_auditoria != 'descuadre':
            raise UserError(_('Solo aplica cuando hay un descuadre registrado.'))
        self.line_ids.with_context(bypass_conteo_lock=True).write({
            'cantidad_segundo_conteo': 0.0, 'segundo_conteo_realizado': False,
        })
        self.write({'estado_auditoria': 'segundo_conteo'})
        self.message_post(
            body=_('SEGUNDO CONTEO solicitado por %s.') % self.env.user.name,
            subtype_xmlid='mail.mt_note',
        )

    def action_confirmar_segundo_conteo(self):
        self.ensure_one()
        if self.estado_auditoria != 'segundo_conteo':
            raise UserError(_('No hay segundo conteo en progreso.'))
        pendientes = self.line_ids.filtered(lambda l: l.tiene_descuadre and not l.segundo_conteo_realizado)
        if pendientes:
            raise UserError(
                _('Productos no recontados:\n%s') % ', '.join(pendientes.mapped('product_id.name'))
            )
        for line in self.line_ids.filtered('tiene_descuadre'):
            line.with_context(bypass_conteo_lock=True).write({'cantidad_recibida': line.cantidad_segundo_conteo})
            line._compute_descuadre()
        self.write({'segundo_conteo_realizado': True})
        if self.tiene_descuadre:
            self.write({'estado_auditoria': 'descuadre'})
            descuadres = self.line_ids.filtered('tiene_descuadre')
            detalle = '\n'.join([
                '• %s: pedido %.2f / recibido %.2f / diferencia %+.2f' % (
                    l.product_id.name, l.cantidad, l.cantidad_recibida, l.diferencia_conteo
                ) for l in descuadres
            ])
            self.message_post(
                body=_('Segundo conteo: descuadre PERSISTE.\n\n%s\n\nUse "Aplicar Excepción" para continuar.') % detalle,
                subtype_xmlid='mail.mt_note',
            )
        else:
            self.write({
                'estado_auditoria': 'auditado',
                'auditado_por_id': self.env.user.id,
                'fecha_auditoria': fields.Datetime.now(),
            })
            self.message_post(
                body=_('Segundo conteo: descuadre RESUELTO. Auditado por %s.') % self.env.user.name,
                subtype_xmlid='mail.mt_note',
            )

    def action_aplicar_excepcion(self):
        self.ensure_one()
        if self.estado_auditoria != 'descuadre':
            raise UserError(_('Solo aplica cuando hay un descuadre confirmado.'))
        return {
            'name': _('Justificación de Excepción'),
            'type': 'ir.actions.act_window',
            'res_model': 'carga.internacional.excepcion.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_carga_id': self.id, 'default_company_id': self.company_id.id},
        }

    def action_marcar_auditado(self):
        self.ensure_one()
        if self.tiene_descuadre and not self.excepcion_justificada:
            raise UserError(
                _('No se puede auditar con descuadres sin justificar.\n'
                  'Use "Aplicar Excepción" o realice un segundo conteo.')
            )
        self.write({
            'estado_auditoria': 'auditado',
            'auditado_por_id': self.env.user.id,
            'fecha_auditoria': fields.Datetime.now(),
        })
        self.message_post(
            body=_('Auditoría COMPLETADA por %s.') % self.env.user.name,
            subtype_xmlid='mail.mt_note',
        )

    # ════════════════════════════════════════════════════════════════════════
    # VALIDACIÓN EN INVENTARIO
    # ════════════════════════════════════════════════════════════════════════

    def _validar_recepciones(self):
        """
        Valida las recepciones (WH/IN) vinculadas a esta carga.
        Para productos sin serial/lote: completa la cantidad automáticamente.
        Para productos con serial/lote: deja que Odoo los pida en el WH/IN
        (el usuario los ingresa directamente en la recepción).
        """
        for rec in self:
            pickings_pendientes = rec.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
            )
            if not pickings_pendientes:
                if not rec.picking_ids:
                    rec.message_post(
                        body=_('No se encontraron recepciones pendientes. '
                               'Verifique que las OC estén confirmadas.'),
                        subtype_xmlid='mail.mt_note',
                    )
                return

            validadas = []
            requieren_seriales = []

            for picking in pickings_pendientes:
                try:
                    if picking.state == 'draft':
                        picking.action_confirm()
                    if picking.state in ('confirmed', 'waiting', 'partially_available'):
                        picking.action_assign()

                    # Detectar si algún move requiere serial/lote sin asignar
                    moves_con_serial = picking.move_ids.filtered(
                        lambda m: m.state not in ('done', 'cancel')
                        and m.product_id.tracking in ('serial', 'lot')
                    )
                    moves_sin_serial = picking.move_ids.filtered(
                        lambda m: m.state not in ('done', 'cancel')
                        and m.product_id.tracking == 'none'
                    )

                    # Completar cantidad en productos sin tracking
                    for move in moves_sin_serial:
                        if move.move_line_ids:
                            for ml in move.move_line_ids:
                                ml.quantity = ml.reserved_uom_qty
                        else:
                            move.quantity = move.product_uom_qty

                    if moves_con_serial:
                        # Registrar para avisar al usuario
                        prods = ', '.join(moves_con_serial.mapped('product_id.display_name'))
                        requieren_seriales.append('%s: %s' % (picking.name, prods))
                        # Intentar validar igual — si Odoo lo permite sin seriales, bien;
                        # si no, el usuario los ingresa en el WH/IN
                        try:
                            picking.with_context(
                                skip_immediate=True, skip_backorder=True,
                            ).button_validate()
                            validadas.append(picking.name)
                        except Exception:
                            # No se pudo validar sin seriales — queda pendiente en WH/IN
                            rec.message_post(
                                body=_(
                                    'La recepción <b>%s</b> quedó pendiente porque tiene '
                                    'productos serializables (%s).<br/>'
                                    'Ingrese los números de serie directamente en el WH/IN '
                                    'y valide desde allí.'
                                ) % (picking.name, prods),
                                subtype_xmlid='mail.mt_note',
                            )
                    else:
                        picking.with_context(
                            skip_immediate=True, skip_backorder=True,
                        ).button_validate()
                        validadas.append(picking.name)

                except Exception as e:
                    _logger.error('CARGA %s — Error en recepción %s: %s',
                                  rec.name, picking.name, str(e), exc_info=True)
                    rec.message_post(
                        body=_('Error al procesar recepción %s: %s') % (picking.name, str(e)),
                        subtype_xmlid='mail.mt_note',
                    )

            if validadas:
                rec.message_post(
                    body=_('%d recepción(es) validadas automáticamente: %s') % (
                        len(validadas), ', '.join(validadas)),
                    subtype_xmlid='mail.mt_note',
                )
            if requieren_seriales:
                rec.message_post(
                    body=_(
                        '<b>⚠️ Recepciones con productos serializables pendientes de serial:</b><br/>%s<br/>'
                        'Abra el WH/IN correspondiente, ingrese los números de serie y valide.'
                    ) % '<br/>'.join(requieren_seriales),
                    subtype_xmlid='mail.mt_note',
                )

    # ════════════════════════════════════════════════════════════════════════
    # ACCIONES AUXILIARES
    # ════════════════════════════════════════════════════════════════════════

    def action_ver_recepciones(self):
        self.ensure_one()
        self._adopt_existing_pickings()
        pickings = self.picking_ids
        if not pickings:
            raise UserError(_('No hay recepciones vinculadas. Verifique que las OC estén confirmadas.'))
        action = {
            'name': _('Recepciones de Inventario'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pickings.ids)],
            'context': {'create': False},
        }
        if len(pickings) == 1:
            action['view_mode'] = 'form'
            action['res_id'] = pickings.id
        return action

    def action_imprimir_informe_conteo(self):
        return self.env.ref('carga_internacional.action_report_informe_conteo').report_action(self)

    def action_adoptar_recepciones(self):
        self.ensure_one()
        self._adopt_existing_pickings()
        after = len(self.picking_ids)
        self.message_post(
            body=_('Recepciones sincronizadas. Total vinculadas: %d.') % after,
            subtype_xmlid='mail.mt_note',
        )
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _('Recepciones sincronizadas'),
                'message': _('%d recepción(es) vinculadas.') % after,
                'sticky': False, 'type': 'success',
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# LÍNEAS DE CARGA
# ══════════════════════════════════════════════════════════════════════════════
class CargaInternacionalLine(models.Model):
    _name = 'carga.internacional.line'
    _description = 'Línea de Carga Internacional'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Secuencia', default=10)
    carga_id = fields.Many2one('carga.internacional', string='Carga', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='carga_id.company_id', store=True, readonly=True, index=True)
    purchase_line_id = fields.Many2one('purchase.order.line', string='Línea de OC', ondelete='set null')

    product_id = fields.Many2one('product.product', string='Producto', required=True,
                                  domain="[('purchase_ok', '=', True)]")
    ref_interna = fields.Char(string='Ref. Interna', related='product_id.default_code', store=True, readonly=True)
    # Solo informativo — indica que el producto requiere serial/lote en inventario
    tracking = fields.Selection(related='product_id.tracking', store=True, readonly=True, string='Trazabilidad')

    cantidad = fields.Float(string='Cant. Pedida', digits='Product Unit of Measure', default=1.0)
    costo_unitario = fields.Float(string='Costo Unit.', digits='Product Price')
    subtotal = fields.Float(string='Subtotal', compute='_compute_subtotal', store=True, digits='Product Price')
    currency_id = fields.Many2one(related='carga_id.currency_id', store=True, readonly=True)

    cantidad_recibida = fields.Float(string='Cant. Recibida (1er Conteo)', digits='Product Unit of Measure', default=0.0)
    conteo_realizado = fields.Boolean(string='Contado', default=False)
    cantidad_segundo_conteo = fields.Float(string='Cant. 2do Conteo', digits='Product Unit of Measure', default=0.0)
    segundo_conteo_realizado = fields.Boolean(string='2do Conteo OK', default=False)
    diferencia_conteo = fields.Float(string='Diferencia', compute='_compute_descuadre_field',
                                      store=True, digits='Product Unit of Measure')
    tiene_descuadre = fields.Boolean(string='Descuadre', compute='_compute_descuadre_field', store=True)
    observacion_conteo = fields.Char(string='Observación')

    @api.depends('cantidad', 'costo_unitario')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.cantidad * line.costo_unitario

    @api.depends('cantidad', 'cantidad_recibida', 'conteo_realizado')
    def _compute_descuadre_field(self):
        for line in self:
            if line.conteo_realizado:
                line.diferencia_conteo = line.cantidad_recibida - line.cantidad
                line.tiene_descuadre = abs(line.diferencia_conteo) > 0.001
            else:
                line.diferencia_conteo = 0.0
                line.tiene_descuadre = False

    def _compute_descuadre(self):
        self._compute_descuadre_field()

    def write(self, vals):
        if 'cantidad_recibida' in vals or 'conteo_realizado' in vals:
            for line in self:
                if line.carga_id.estado_auditoria not in ('en_conteo', 'sin_auditar'):
                    if not self.env.context.get('bypass_conteo_lock'):
                        raise UserError(
                            _('El campo "Cant. Recibida" solo se puede editar en estado "En Conteo".\n'
                              'Estado actual: %s') % line.carga_id.estado_auditoria
                        )
        if 'cantidad_segundo_conteo' in vals or 'segundo_conteo_realizado' in vals:
            for line in self:
                if line.carga_id.estado_auditoria not in ('segundo_conteo',):
                    if not self.env.context.get('bypass_conteo_lock'):
                        raise UserError(
                            _('El campo "Cant. 2do Conteo" solo se puede editar en estado "Segundo Conteo".\n'
                              'Estado actual: %s') % line.carga_id.estado_auditoria
                        )
        return super().write(vals)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.costo_unitario = self.product_id.standard_price or self.product_id.list_price or 0.0

    @api.onchange('cantidad_recibida')
    def _onchange_cantidad_recibida(self):
        if self.cantidad_recibida >= 0:
            self.conteo_realizado = True


# ══════════════════════════════════════════════════════════════════════════════
# INCIDENCIAS
# ══════════════════════════════════════════════════════════════════════════════
class CargaInternacionalIncidencia(models.Model):
    _name = 'carga.internacional.incidencia'
    _description = 'Incidencia de Carga Internacional'
    _order = 'fecha desc, id desc'

    carga_id = fields.Many2one('carga.internacional', string='Carga', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='carga_id.company_id', store=True, readonly=True, index=True)
    fecha = fields.Datetime(string='Fecha', default=fields.Datetime.now, required=True)
    tipo = fields.Selection(
        [('caja_danada', 'Caja Dañada'), ('mercancia_danada', 'Mercancía Dañada'),
         ('faltante', 'Faltante'), ('sobrante', 'Sobrante'),
         ('producto_incorrecto', 'Producto Incorrecto'), ('empaque_deficiente', 'Empaque Deficiente'),
         ('humedad', 'Humedad / Mojado'), ('otro', 'Otro')],
        string='Tipo de Incidencia', required=True,
    )
    descripcion = fields.Text(string='Descripción', required=True)
    product_id = fields.Many2one('product.product', string='Producto Afectado')
    cantidad_afectada = fields.Float(string='Cantidad Afectada')
    reportado_por_id = fields.Many2one('res.users', string='Reportado por', default=lambda self: self.env.user)
    foto = fields.Binary(string='Foto', attachment=True)
    foto_nombre = fields.Char(string='Nombre Foto')
    resuelto = fields.Boolean(string='Resuelto', default=False)
    resolucion = fields.Text(string='Resolución')


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD EXCEPCIÓN
# ══════════════════════════════════════════════════════════════════════════════
class CargaInternacionalExcepcionWizard(models.TransientModel):
    _name = 'carga.internacional.excepcion.wizard'
    _description = 'Wizard para Justificar Excepción de Descuadre'

    carga_id = fields.Many2one('carga.internacional', string='Carga', required=True)
    company_id = fields.Many2one(related='carga_id.company_id', store=True, readonly=True)
    justificacion = fields.Text(string='Justificación', required=True,
        help='Explique por qué hay productos faltantes, sobrantes o con diferencias.')
    tipo_excepcion = fields.Selection(
        [('faltante_proveedor', 'Faltante en origen (proveedor)'),
         ('dano_transporte', 'Daño durante el transporte'),
         ('error_conteo', 'Error de conteo justificado'),
         ('sobrante_proveedor', 'Sobrante enviado por proveedor'),
         ('diferencia_aceptable', 'Diferencia dentro del margen aceptable'),
         ('otro', 'Otro — ver justificación')],
        string='Tipo de Excepción', required=True,
    )
    linea_ids = fields.Many2many(
        'carga.internacional.line', 'carga_excepcion_wiz_line_rel', 'wizard_id', 'line_id',
        string='Líneas Afectadas',
        domain="[('carga_id', '=', carga_id), ('tiene_descuadre', '=', True)]",
    )

    def action_confirmar_excepcion(self):
        self.ensure_one()
        if not self.justificacion or len(self.justificacion.strip()) < 20:
            raise ValidationError(_('La justificación debe tener al menos 20 caracteres.'))
        carga = self.carga_id
        carga.write({
            'excepcion_justificada': True,
            'excepcion_justificacion': '[%s]\n%s' % (
                dict(self._fields['tipo_excepcion'].selection).get(self.tipo_excepcion, ''),
                self.justificacion,
            ),
            'excepcion_usuario_id': self.env.user.id,
            'excepcion_fecha': fields.Datetime.now(),
            'estado_auditoria': 'excepcion',
        })
        carga.message_post(
            body=_('EXCEPCIÓN aplicada por %s.\n\nTipo: %s\n\nJustificación:\n%s') % (
                self.env.user.name,
                dict(self._fields['tipo_excepcion'].selection).get(self.tipo_excepcion, ''),
                self.justificacion,
            ),
            subtype_xmlid='mail.mt_note',
        )
        return {'type': 'ir.actions.act_window_close'}
