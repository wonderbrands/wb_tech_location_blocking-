# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError
from odoo import fields

@tagged('post_install', '-at_install')
class TestLocationBlocking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Find or create stock user and leader user
        cls.stock_user_group = cls.env.ref('stock.group_stock_user')
        cls.leader_group = cls.env.ref('wb_tech_location_blocking.group_lider_de_turno')

        cls.operator_user = cls.env['res.users'].create({
            'name': 'Test Operator',
            'login': 'test_operator',
            'email': 'operator@test.com',
            'groups_id': [(6, 0, [cls.stock_user_group.id])]
        })

        cls.leader_user = cls.env['res.users'].create({
            'name': 'Test Leader',
            'login': 'test_leader',
            'email': 'leader@test.com',
            'groups_id': [(6, 0, [cls.stock_user_group.id, cls.leader_group.id])]
        })

        # Create locations
        cls.wh_stock = cls.env['stock.location'].create({
            'name': 'WH/Stock',
            'usage': 'view',
        })

        cls.pasillo_a = cls.env['stock.location'].create({
            'name': 'Pasillo A',
            'location_id': cls.wh_stock.id,
            'usage': 'internal',
        })

        cls.pos1 = cls.env['stock.location'].create({
            'name': 'Posicion 1',
            'location_id': cls.pasillo_a.id,
            'usage': 'internal',
        })

        cls.pos2 = cls.env['stock.location'].create({
            'name': 'Posicion 2',
            'location_id': cls.pasillo_a.id,
            'usage': 'internal',
        })

        # Ensure blocked parent and sub-locations exist
        cls.location_blocked = cls.env.ref('wmds.location_blocked')
        cls.location_blocked_ciclico = cls.env.ref('wb_tech_location_blocking.location_blocked_ciclico')
        cls.location_blocked_no_apto = cls.env.ref('wb_tech_location_blocking.location_blocked_no_apto')
        cls.location_blocked_sobredimensionada = cls.env.ref('wb_tech_location_blocking.location_blocked_sobredimensionada')
        
        # Look up or create WH/Cuarentena for tests
        wh = cls.env['stock.location'].search([('name', '=', 'WH'), ('location_id', '=', False)], limit=1)
        if not wh:
            wh = cls.env['stock.location'].create({
                'name': 'WH',
                'usage': 'view'
            })
        cls.location_blocked_cuarentena = cls.env['stock.location'].search([('complete_name', '=', 'WH/Cuarentena')], limit=1)
        if not cls.location_blocked_cuarentena:
            cls.location_blocked_cuarentena = cls.env['stock.location'].create({
                'name': 'Cuarentena',
                'location_id': wh.id,
                'usage': 'internal'
            })

        cls.location_blocked_danado = cls.env.ref('wb_tech_location_blocking.location_blocked_danado')
        cls.location_blocked_onsite = cls.env.ref('wb_tech_location_blocking.location_blocked_onsite')

    def test_01_operator_blocking_ciclico(self):
        """Test blocking and unblocking with 'ciclico' reason by writing directly simulating wmds."""
        # Block directly simulating wmds
        self.pos1.sudo().write({
            'location_id': self.location_blocked_ciclico.id,
            'block_reason_type': 'ciclico',
            'block_reason': 'Conteo Cíclico: TEST-01',
            'original_parent_id': self.pasillo_a.id,
            'block_date': fields.Datetime.now(),
            'block_user_id': self.operator_user.id
        })

        # Check location state
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_ciclico.id)
        self.assertEqual(self.pos1.block_reason_type, 'ciclico')
        self.assertEqual(self.pos1.original_parent_id.id, self.pasillo_a.id)

        # Try to unblock manually -> must raise UserError
        with self.assertRaises(UserError):
            self.pos1.with_user(self.operator_user).action_unblock()

        # Simulate wmds unblocking by writing directly
        self.pos1.sudo().write({
            'location_id': self.pos1.original_parent_id.id,
            'block_reason_type': False,
            'block_reason': False,
            'original_parent_id': False
        })

        # Check restored state
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos1.block_reason_type)
        self.assertFalse(self.pos1.original_parent_id)

    def test_02_ciclico_block_with_pending_moves(self):
        """Test that we cannot block as 'ciclico' using the block wizard (raising ValueError due to selection)."""
        with self.assertRaises(ValueError):
            self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
                'location_ids': [(6, 0, [self.pos1.id])],
                'block_reason_type': 'ciclico',
                'comment': 'Test fail'
            })

    def test_03_no_apto_blocking_permissions_and_validations(self):
        """Test permissions and validations for 'no_apto' blocking."""
        # 1. Non-leader tries to block as no_apto -> raises UserError
        wizard1 = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'no_apto',
            'ticket': 'TICK-101',
            'comment': 'Operator block no apto'
        })
        with self.assertRaises(UserError):
            wizard1.action_block()

        # 3. Leader tries to block as no_apto WITH product in position -> raises UserError
        # Place some quant
        product = self.env['product.product'].create({
            'name': 'Test Product 2',
            'type': 'consu',
            'is_storable': True,
        })
        self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': self.pos1.id,
            'quantity': 5.0,
            'company_id': self.env.company.id,
        })
        
        wizard3 = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'no_apto',
            'ticket': 'TICK-102',
            'comment': 'Block with product'
        })
        with self.assertRaises(UserError):
            wizard3.action_block()

    def test_04_no_apto_successful_block_and_unlock(self):
        """Test successful block as 'no_apto' by leader and confirmation wizard for unblocking."""
        # Block by leader
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'no_apto',
            'ticket': 'TICK-999',
            'comment': 'No apto block successful'
        })
        wizard.action_block()

        self.assertEqual(self.pos1.location_id.id, self.location_blocked_no_apto.id)
        self.assertEqual(self.pos1.block_reason_type, 'no_apto')
        self.assertEqual(self.pos1.block_ticket, 'TICK-999')

        # Try to unblock by operator -> raises UserError
        with self.assertRaises(UserError):
            self.pos1.with_user(self.operator_user).action_unblock()

        # Leader clicks action_unblock -> returns confirmation wizard action
        action = self.pos1.with_user(self.leader_user).action_unblock()
        self.assertEqual(action.get('res_model'), 'wb.stock.location.unblock.wizard')

        # Instantiate unblock wizard
        unblock_wiz = self.env['wb.stock.location.unblock.wizard'].with_user(self.leader_user).create({
            'location_id': self.pos1.id,
            'is_repaired': False,
            'comment': 'Attempt unblocking'
        })
        
        # Confirm with is_repaired=False -> raises UserError
        with self.assertRaises(UserError):
            unblock_wiz.action_confirm_unblock()

        # Confirm with is_repaired=True -> successfully unblocks
        unblock_wiz.is_repaired = True
        unblock_wiz.action_confirm_unblock()

        # Check restored state
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos1.block_reason_type)

    def test_05_no_apto_blocking_by_leader(self):
        """Test blocking validations and permissions for no_apto by leader."""
        # 1. Block as No Apta (Only leader can execute, requires ticket, goes to location_blocked_no_apto)
        # Operator tries to block as no_apto -> raises error
        wizard_no_apto_fail = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'no_apto',
            'ticket': 'TICK-M1',
        })
        with self.assertRaises(UserError):
            wizard_no_apto_fail.action_block()

        # Leader blocks as no_apto
        wizard_no_apto = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'no_apto',
            'ticket': 'TICK-M2',
            'comment': 'Broken shelves'
        })
        wizard_no_apto.action_block()
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_no_apto.id)
        self.assertEqual(self.pos1.block_reason_type, 'no_apto')
        self.assertEqual(self.pos1.block_ticket, 'TICK-M2')

    def test_06_block_expiration_and_warning(self):
        """Test block expiration date setting and the is_block_expired compute alert field."""
        # Block with future expiration date as leader (no_apto)
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'no_apto',
            'ticket': 'TICK-EXP1',
            'expiration_date': fields.Date.from_string('2099-12-31'),
            'comment': 'Future block'
        })
        wizard.action_block()
        
        self.assertEqual(self.pos1.block_expiration_date, fields.Date.from_string('2099-12-31'))
        self.assertFalse(self.pos1.is_block_expired)

        # Unblock and re-block with past expiration date
        action = self.pos1.with_user(self.leader_user).action_unblock()
        unblock_wiz = self.env['wb.stock.location.unblock.wizard'].with_user(self.leader_user).create({
            'location_id': self.pos1.id,
            'is_repaired': True,
            'comment': 'Restore for exp test'
        })
        unblock_wiz.action_confirm_unblock()
        
        wizard_expired = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'no_apto',
            'ticket': 'TICK-EXP2',
            'expiration_date': fields.Date.from_string('2020-01-01'),
            'comment': 'Expired block'
        })
        wizard_expired.action_block()

        self.assertEqual(self.pos1.block_expiration_date, fields.Date.from_string('2020-01-01'))
        self.assertTrue(self.pos1.is_block_expired)

    def test_07_mass_blocking(self):
        """Test mass blocking multiple locations in a single wizard action."""
        # Block pos1 and pos2 as no_apto in bulk
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id, self.pos2.id])],
            'block_reason_type': 'no_apto',
            'ticket': 'TICK-MASS',
            'comment': 'Bulk block test'
        })
        wizard.action_block()

        # Both should be blocked
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_no_apto.id)
        self.assertEqual(self.pos2.location_id.id, self.location_blocked_no_apto.id)
        self.assertEqual(self.pos1.block_reason_type, 'no_apto')
        self.assertEqual(self.pos2.block_reason_type, 'no_apto')

    def test_08_cuarentena_blocking_and_unblocking_validation(self):
        """Test blocking as 'cuarentena' and validating that unblocking is not allowed."""
        # Block directly on location
        self.pos1.sudo().write({
            'location_id': self.location_blocked_cuarentena.id,
            'block_reason_type': 'cuarentena',
            'block_reason': 'Test quarantine block',
            'original_parent_id': self.pasillo_a.id
        })

        # Check location state
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_cuarentena.id)
        self.assertEqual(self.pos1.block_reason_type, 'cuarentena')

        # Try to unblock -> raises UserError
        with self.assertRaises(UserError):
            self.pos1.with_user(self.operator_user).action_unblock()

    def test_09_sobredimensionada_blocking(self):
        """Test blocking as 'sobredimensionada' via oversized wizard and unblocking successfully."""
        # 1. Place some product stock in pos2 and pos1
        product = self.env['product.product'].create({
            'name': 'Test Product 3',
            'type': 'consu',
            'is_storable': True,
        })
        quant = self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': self.pos2.id,
            'quantity': 5.0,
            'company_id': self.env.company.id,
        })
        # Place stock in pos1 (the location we oversize from) so it doesn't auto-unblock pos2 immediately
        self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': self.pos1.id,
            'quantity': 10.0,
            'company_id': self.env.company.id,
        })

        # Try to block pos2 -> raises UserError because of stock
        wizard_fail = self.env['wb.stock.location.oversized.wizard'].with_user(self.operator_user).create({
            'original_location_id': self.pos1.id,
            'location_ids': [(6, 0, [self.pos2.id])],
        })
        with self.assertRaises(UserError):
            wizard_fail.action_block_oversized()

        # Remove the stock
        quant.unlink()

        # Block should succeed now
        wizard = self.env['wb.stock.location.oversized.wizard'].with_user(self.operator_user).create({
            'original_location_id': self.pos1.id,
            'location_ids': [(6, 0, [self.pos2.id])],
        })
        wizard.action_block_oversized()

        # Check location state of the blocked location pos2
        self.assertEqual(self.pos2.location_id.id, self.location_blocked_sobredimensionada.id)
        self.assertEqual(self.pos2.block_reason_type, 'sobredimensionada')
        # Crucial: its original parent should remain its OWN parent (pasillo_a)
        self.assertEqual(self.pos2.original_parent_id.id, self.pasillo_a.id)
        # And oversized_from_location_id points to pos1 (where we oversized from)
        self.assertEqual(self.pos2.oversized_from_location_id.id, self.pos1.id)
        # Verify the One2many field has the blocked location
        self.assertIn(self.pos2.id, self.pos1.oversized_location_ids.ids)

        # Unblock pos2 should be allowed and restore the location parent to pasillo_a
        self.pos2.with_user(self.operator_user).action_unblock()
        self.assertEqual(self.pos2.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos2.block_reason_type)
        self.assertFalse(self.pos2.original_parent_id)
        self.assertFalse(self.pos2.oversized_from_location_id)
        # Verify the One2many field is cleared
        self.assertNotIn(self.pos2.id, self.pos1.oversized_location_ids.ids)

    def test_10_cuarentena_robust_unblocking_validation(self):
        """Test robust quarantine check for unblocking (e.g. if reason text contains cuarentena or parent is Cuarentena)."""
        # Block with reason_type no_apto but comment containing 'cuarentena'
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'no_apto',
            'ticket': 'TICK-QUAR',
            'comment': 'Puesto en cuarentena temporal'
        })
        wizard.action_block()

        # Try to unblock -> raises UserError because comment has 'cuarentena'
        with self.assertRaises(UserError):
            self.pos1.with_user(self.leader_user).action_unblock()

        # Unblock by overriding reason to test the other condition (parent location containing 'cuarentena')
        self.pos1.sudo().write({
            'block_reason': 'No comment',
            'location_id': self.location_blocked_cuarentena.id,
        })
        # Try to unblock -> raises UserError because parent is a Cuarentena location
        with self.assertRaises(UserError):
            self.pos1.with_user(self.leader_user).action_unblock()

    def test_11_nomenclature_fields(self):
        """Test parsing and storage of nomenclature components (pasillo, posicion, frente, nivel)."""
        location = self.env['stock.location'].create({
            'name': 'A-P03-F1-N2',
            'usage': 'internal',
        })
        self.assertEqual(location.loc_pasillo, 'A')
        self.assertEqual(location.loc_posicion, 'P03')
        self.assertEqual(location.loc_frente, 'F1')
        self.assertEqual(location.loc_nivel, 'N2')

        # Test location with non-matching pattern
        location_non_matching = self.env['stock.location'].create({
            'name': 'Pasillo 5',
            'usage': 'internal',
        })
        self.assertFalse(location_non_matching.loc_pasillo)
        self.assertFalse(location_non_matching.loc_posicion)
        self.assertFalse(location_non_matching.loc_frente)
        self.assertFalse(location_non_matching.loc_nivel)

    def test_12_wmds_auto_routing_and_history(self):
        """Test that writing to wmds.location_blocked (simulating wmds) auto-routes to sub-locations and logs history."""
        # 1. Simulate wmds blocking by writing parent location
        self.pos1.sudo().write({
            'original_parent_id': self.pasillo_a.id,
            'location_id': self.env.ref('wmds.location_blocked').id,
            'block_reason': 'Conteo Cíclico: TEST-WMDS-AUTO'
        })

        # Verify auto-routing and metadata
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_ciclico.id)
        self.assertEqual(self.pos1.block_reason_type, 'ciclico')
        self.assertTrue(self.pos1.block_date)
        self.assertTrue(self.pos1.block_user_id)

        # Verify history was created automatically
        history = self.env['stock.location.block.history'].search([('location_id', '=', self.pos1.id)])
        self.assertEqual(len(history), 1)
        self.assertEqual(history.event_type, 'block')
        self.assertEqual(history.block_reason_type, 'ciclico')
        self.assertEqual(history.block_reason, 'Conteo Cíclico: TEST-WMDS-AUTO')

        # 2. Simulate wmds unblocking by clearing original_parent_id and block_reason
        self.pos1.sudo().write({
            'location_id': self.pos1.original_parent_id.id,
            'block_reason': False,
            'original_parent_id': False
        })

        # Verify parent restored and metadata cleared
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos1.block_reason_type)
        self.assertFalse(self.pos1.block_date)
        self.assertFalse(self.pos1.block_user_id)

        # Verify unblock history was created automatically
        history_after = self.env['stock.location.block.history'].search([('location_id', '=', self.pos1.id)], order='id desc')
        self.assertEqual(len(history_after), 2)
        self.assertEqual(history_after[0].event_type, 'unblock')

    def test_13_is_empty_location_field(self):
        """Test is_empty_location field computation and search logic."""
        # By default pos1 is empty
        self.assertTrue(self.pos1.is_empty_location)

        # Place some stock
        product = self.env['product.product'].create({
            'name': 'Test Product Empty Search',
            'type': 'consu',
            'is_storable': True,
        })
        quant = self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': self.pos1.id,
            'quantity': 10.0,
            'company_id': self.env.company.id,
        })

        # Now pos1 is NOT empty
        self.pos1._compute_is_empty_location()
        self.assertFalse(self.pos1.is_empty_location)

        # Search for empty locations
        empty_locations = self.env['stock.location'].search([
            ('id', 'in', [self.pos1.id, self.pos2.id]),
            ('is_empty_location', '=', True)
        ])
        self.assertNotIn(self.pos1.id, empty_locations.ids)
        self.assertIn(self.pos2.id, empty_locations.ids)

        # Search for non-empty locations
        non_empty_locations = self.env['stock.location'].search([
            ('id', 'in', [self.pos1.id, self.pos2.id]),
            ('is_empty_location', '=', False)
        ])
        self.assertIn(self.pos1.id, non_empty_locations.ids)
        self.assertNotIn(self.pos2.id, non_empty_locations.ids)

        # Clean up
        quant.unlink()
        self.pos1._compute_is_empty_location()
        self.assertTrue(self.pos1.is_empty_location)

    def test_14_danado_and_onsite_blocking_validation(self):
        """Test blocking and unblocking validation for danado and onsite reasons."""
        # 1. Non-leader tries to block as danado/onsite -> raises UserError
        wiz_danado_fail = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'danado',
            'ticket': 'TICK-D1',
        })
        with self.assertRaises(UserError):
            wiz_danado_fail.action_block()

        # 2. Leader blocks as danado (requires ticket)
        wiz_danado = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'danado',
            'ticket': 'TICK-D2',
            'comment': 'Shelf broken'
        })
        wiz_danado.action_block()
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_danado.id)
        self.assertEqual(self.pos1.block_reason_type, 'danado')
        self.assertEqual(self.pos1.block_ticket, 'TICK-D2')

        # 3. Leader unblocks it (requires confirmation wizard)
        action = self.pos1.with_user(self.leader_user).action_unblock()
        self.assertEqual(action.get('res_model'), 'wb.stock.location.unblock.wizard')
        unblock_wiz = self.env['wb.stock.location.unblock.wizard'].with_user(self.leader_user).create({
            'location_id': self.pos1.id,
            'is_repaired': True,
        })
        unblock_wiz.action_confirm_unblock()
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)

        # 4. Leader blocks as onsite
        wiz_onsite = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'onsite',
            'comment': 'Onsite audit'
        })
        wiz_onsite.action_block()
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_onsite.id)
        self.assertEqual(self.pos1.block_reason_type, 'onsite')

        # 5. Non-leader tries to unblock onsite -> raises UserError
        with self.assertRaises(UserError):
            self.pos1.with_user(self.operator_user).action_unblock()

        # 6. Leader unblocks onsite (goes through wizard)
        action = self.pos1.with_user(self.leader_user).action_unblock()
        self.assertEqual(action.get('res_model'), 'wb.stock.location.unblock.wizard')
        unblock_wiz = self.env['wb.stock.location.unblock.wizard'].with_user(self.leader_user).create({
            'location_id': self.pos1.id,
            'is_repaired': True,
        })
        unblock_wiz.action_confirm_unblock()
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)

    def test_15_rackeo_picking_comex_blocking(self):
        """Test that validating a 'Rackeo' picking blocks destination locations if COMEX lacks Vo.Bo."""
        # Create a product for moving
        product = self.env['product.product'].create({
            'name': 'COMEX Block Test Product',
            'type': 'consu',
            'is_storable': True,
        })

        # Create picking type 'Rackeo'
        warehouse = self.env['stock.warehouse'].search([], limit=1)
        picking_type = self.env['stock.picking.type'].create({
            'name': 'Rackeo',
            'code': 'internal',
            'sequence_code': 'RACK_TEST',
            'warehouse_id': warehouse.id,
        })

        # Create a PO with check_commertial = False (Lacks Vo.Bo.)
        partner = self.env['res.partner'].create({'name': 'COMEX Partner'})
        po_no_vobo = self.env['purchase.order'].create({
            'partner_id': partner.id,
            'name': 'PO_NO_VOBO_123',
            'check_commertial': False,
        })

        # Create a picking of type 'Rackeo' with origin = 'COMEX: PO_NO_VOBO_123'
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': 'COMEX: PO_NO_VOBO_123',
            'location_id': self.pasillo_a.id,
            'location_dest_id': self.pos1.id,
        })

        # Create a stock move to pos1
        move = self.env['stock.move'].create({
            'name': 'Rackeo Move 1',
            'product_id': product.id,
            'product_uom_qty': 1.0,
            'product_uom': product.uom_id.id,
            'picking_id': picking.id,
            'location_id': self.pasillo_a.id,
            'location_dest_id': self.pos1.id,
            'quantity': 1.0,
        })

        # Verify target location pos1 is not blocked and has its original parent
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos1.block_reason_type)

        # Validate the picking
        picking.action_confirm()
        picking.button_validate()

        # Target location should be blocked under Cuarentena now
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_cuarentena.id)
        self.assertEqual(self.pos1.block_reason_type, 'cuarentena')
        self.assertEqual(self.pos1.original_parent_id.id, self.pasillo_a.id)

        # 1. Test auto-unblock when PO Vo.Bo. is granted (check_commertial = True)
        po_no_vobo.write({'check_commertial': True})
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos1.block_reason_type)
        self.assertFalse(self.pos1.original_parent_id)

        # Clean up stock from first picking validation in pos1 so it is empty for the next validation
        self.env['stock.quant'].search([('location_id', '=', self.pos1.id)]).unlink()

        # 2. Test with Vo.Bo. (check_commertial = True) on a new PO and picking
        po_with_vobo = self.env['purchase.order'].create({
            'partner_id': partner.id,
            'name': 'PO_WITH_VOBO_123',
            'check_commertial': True,
        })

        picking_vobo = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': 'COMEX: PO_WITH_VOBO_123',
            'location_id': self.pasillo_a.id,
            'location_dest_id': self.pos1.id,
        })

        move_vobo = self.env['stock.move'].create({
            'name': 'Rackeo Move 2',
            'product_id': product.id,
            'product_uom_qty': 1.0,
            'product_uom': product.uom_id.id,
            'picking_id': picking_vobo.id,
            'location_id': self.pasillo_a.id,
            'location_dest_id': self.pos1.id,
            'quantity': 1.0,
        })

        picking_vobo.action_confirm()
        picking_vobo.button_validate()

        # The location should NOT be blocked
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos1.block_reason_type)

        # 3. Test that validating a Rackeo picking to a non-empty location raises UserError
        # First, add stock to pos1
        quant = self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': self.pos1.id,
            'quantity': 5.0,
            'company_id': self.env.company.id,
        })

        picking_error = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': 'COMEX: PO_WITH_VOBO_123',
            'location_id': self.pasillo_a.id,
            'location_dest_id': self.pos1.id,
        })

        move_error = self.env['stock.move'].create({
            'name': 'Rackeo Move Error',
            'product_id': product.id,
            'product_uom_qty': 1.0,
            'product_uom': product.uom_id.id,
            'picking_id': picking_error.id,
            'location_id': self.pasillo_a.id,
            'location_dest_id': self.pos1.id,
            'quantity': 1.0,
        })

        picking_error.action_confirm()
        with self.assertRaises(UserError):
            picking_error.button_validate()

        # Clean up stock
        quant.unlink()

    def test_16_csv_report_action(self):
        """Test the action_generate_blocked_report_csv returns the correct act_url action."""
        # Block pos1 first
        self.pos1.sudo().write({
            'location_id': self.location_blocked_ciclico.id,
            'block_reason_type': 'ciclico',
            'block_reason': 'Conteo Cíclico: TEST-CSV',
            'original_parent_id': self.pasillo_a.id,
            'block_date': fields.Datetime.now(),
            'block_user_id': self.operator_user.id
        })
        
        # Test with empty self
        action_all = self.env['stock.location'].action_generate_blocked_report_csv()
        self.assertEqual(action_all['type'], 'ir.actions.act_url')
        self.assertEqual(action_all['url'], '/web/blocked_locations_csv')
        self.assertEqual(action_all['target'], 'new')
        
        # Test with self containing records
        action_specific = self.pos1.action_generate_blocked_report_csv()
        self.assertEqual(action_specific['type'], 'ir.actions.act_url')
        self.assertIn('/web/blocked_locations_csv?wizard_id=', action_specific['url'])
        self.assertEqual(action_specific['target'], 'new')

    def test_17_cyclic_counting_blocked_locations_validation(self):
        """Test that blocked locations cannot be selected/counted in scheduled cycle counts."""
        # 1. Block pos1 under ciclico
        self.pos1.sudo().write({
            'location_id': self.location_blocked_ciclico.id,
            'block_reason_type': 'ciclico',
            'block_reason': 'Conteo Cíclico: TEST-BLOCK',
            'original_parent_id': self.pasillo_a.id,
            'block_date': fields.Datetime.now(),
            'block_user_id': self.operator_user.id
        })

        self.assertTrue(self.pos1.is_location_blocked())

        # 2. Try to create scheduled.cycle.count with pos1 -> should raise UserError
        cycle_count = self.env['scheduled.cycle.count'].create({
            'notes': 'Test Cycle Count Blocked Location',
        })

        # Try to add pos1 to scheduled.cycle.count selected locations
        with self.assertRaises(UserError):
            self.env['cycle.count.selected.location'].create({
                'cycle_count_id': cycle_count.id,
                'location_id': self.pos1.id,
            })

        # 3. Try to add pos1 to cycle.count.line of a wave -> should raise UserError
        wave = self.env['cycle.count.wave'].create({
            'cycle_count_id': cycle_count.id,
            'operator_id': self.operator_user.id,
        })

        with self.assertRaises(UserError):
            self.env['cycle.count.line'].create({
                'wave_id': wave.id,
                'stock_location_id': self.pos1.id,
                'qty': 5,
            })

        # 4. Block pos1 under the current cycle_count's name -> should succeed
        self.pos1.sudo().write({
            'block_reason': f"Conteo Cíclico: {cycle_count.name}",
        })

        # It should now be allowed to add pos1 to the cycle count's selected locations
        selected_loc = self.env['cycle.count.selected.location'].create({
            'cycle_count_id': cycle_count.id,
            'location_id': self.pos1.id,
        })
        self.assertTrue(selected_loc)

        # It should also be allowed to add pos1 to the wave lines
        line = self.env['cycle.count.line'].create({
            'wave_id': wave.id,
            'stock_location_id': self.pos1.id,
            'qty': 10,
        })
        self.assertTrue(line)

    def test_18_sobredimensionada_auto_unblock_when_empty(self):
        """Test that blocked locations are automatically unblocked when the origin location runs out of stock."""
        # 1. Place some product stock in pos1 (the location we will oversize from)
        product = self.env['product.product'].create({
            'name': 'Oversized Test Product',
            'type': 'consu',
            'is_storable': True,
        })
        quant = self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': self.pos1.id,
            'quantity': 10.0,
            'company_id': self.env.company.id,
        })

        # 2. Block pos2 pointing to pos1 (oversized_from_location_id = pos1)
        wizard = self.env['wb.stock.location.oversized.wizard'].with_user(self.operator_user).create({
            'original_location_id': self.pos1.id,
            'location_ids': [(6, 0, [self.pos2.id])],
        })
        wizard.action_block_oversized()

        # Check that pos2 is blocked and points to pos1
        self.assertEqual(self.pos2.location_id.id, self.location_blocked_sobredimensionada.id)
        self.assertEqual(self.pos2.block_reason_type, 'sobredimensionada')
        self.assertEqual(self.pos2.oversized_from_location_id.id, self.pos1.id)

        # 3. Reduce stock in pos1 to 0 -> should automatically unblock pos2
        quant.write({'quantity': 0.0})

        self.assertEqual(self.pos2.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos2.block_reason_type)
        self.assertFalse(self.pos2.oversized_from_location_id)

        # Verify history comments
        history = self.env['stock.location.block.history'].search([
            ('location_id', '=', self.pos2.id),
            ('event_type', '=', 'unblock')
        ], order='id desc', limit=1)
        self.assertTrue(history)
        self.assertEqual(history.comment, "Desbloqueado porque se acabó el producto sobredimensionado.")

        # 4. Now test the unlink trigger
        # Put stock in pos1 again
        quant2 = self.env['stock.quant'].create({
            'product_id': product.id,
            'location_id': self.pos1.id,
            'quantity': 5.0,
            'company_id': self.env.company.id,
        })

        # Block pos2 pointing to pos1 again
        wizard2 = self.env['wb.stock.location.oversized.wizard'].with_user(self.operator_user).create({
            'original_location_id': self.pos1.id,
            'location_ids': [(6, 0, [self.pos2.id])],
        })
        wizard2.action_block_oversized()

        self.assertEqual(self.pos2.location_id.id, self.location_blocked_sobredimensionada.id)

        # Unlink the quant (simulate it being deleted/removed from location) -> should trigger auto-unblock
        quant2.unlink()

        self.assertEqual(self.pos2.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos2.block_reason_type)
        self.assertFalse(self.pos2.oversized_from_location_id)

        # Verify history comments again
        history2 = self.env['stock.location.block.history'].search([
            ('location_id', '=', self.pos2.id),
            ('event_type', '=', 'unblock')
        ], order='id desc', limit=1)
        self.assertTrue(history2)
        self.assertEqual(history2.comment, "Desbloqueado porque se acabó el producto sobredimensionado.")

    def test_19_sobredimensionada_unblocks_immediately_if_blocked_when_empty(self):
        """Test that if we try to block a location pointing to an empty origin, it unblocks immediately."""
        # Ensure pos1 is empty (has no stock)
        quants = self.env['stock.quant'].search([('location_id', '=', self.pos1.id)])
        quants.unlink()

        # Try to block pos2 pointing to the empty pos1
        wizard = self.env['wb.stock.location.oversized.wizard'].with_user(self.operator_user).create({
            'original_location_id': self.pos1.id,
            'location_ids': [(6, 0, [self.pos2.id])],
        })
        wizard.action_block_oversized()

        # Check that pos2 remains unblocked (it was blocked, but immediately unblocked because pos1 is empty)
        self.assertEqual(self.pos2.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos2.block_reason_type)
        self.assertFalse(self.pos2.oversized_from_location_id)

        # Verify history comments
        history = self.env['stock.location.block.history'].search([
            ('location_id', '=', self.pos2.id),
            ('event_type', '=', 'unblock')
        ], order='id desc', limit=1)
        self.assertTrue(history)
        self.assertEqual(history.comment, "Desbloqueado porque se acabó el producto sobredimensionado.")

    def test_20_dupla_blocking(self):
        """Test blocking as 'dupla' and validating that only shift leader can block/unblock and it moves under location_blocked_dupla."""
        location_blocked_dupla = self.env.ref('wb_tech_location_blocking.location_blocked_dupla')
        
        # 1. Block with wizard as leader (successful)
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'dupla',
            'comment': 'Test dupla block'
        })
        wizard.action_block()
        
        # Check location state
        self.assertEqual(self.pos1.location_id.id, location_blocked_dupla.id)
        self.assertEqual(self.pos1.block_reason_type, 'dupla')
        self.assertEqual(self.pos1.original_parent_id.id, self.pasillo_a.id)

        # 2. Try to unblock with operator -> raises UserError
        with self.assertRaises(UserError):
            self.pos1.with_user(self.operator_user).action_unblock()

        # 3. Unblock with leader -> success (simulating wizard)
        action = self.pos1.with_user(self.leader_user).action_unblock()
        self.assertEqual(action.get('res_model'), 'wb.stock.location.unblock.wizard')
        
        unblock_wiz = self.env['wb.stock.location.unblock.wizard'].with_user(self.leader_user).create({
            'location_id': self.pos1.id,
            'is_repaired': True,
            'comment': 'Dupla resolved'
        })
        unblock_wiz.action_confirm_unblock()
        
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos1.block_reason_type)
        self.assertFalse(self.pos1.original_parent_id)
