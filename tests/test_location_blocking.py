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
        cls.location_blocked = cls.env.ref('wb_tech_location_blocking.location_blocked')
        cls.location_blocked_ciclico = cls.env.ref('wb_tech_location_blocking.location_blocked_ciclico')
        cls.location_blocked_no_apto = cls.env.ref('wb_tech_location_blocking.location_blocked_no_apto')
        cls.location_blocked_sobredimensionada = cls.env.ref('wb_tech_location_blocking.location_blocked_sobredimensionada')
        cls.location_blocked_cuarentena = cls.env.ref('wb_tech_location_blocking.location_blocked_cuarentena')
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
        # 1. Place some product stock in pos2
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


