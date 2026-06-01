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
        cls.location_blocked_danado = cls.env.ref('wb_tech_location_blocking.location_blocked_danado')
        cls.location_blocked_onsite = cls.env.ref('wb_tech_location_blocking.location_blocked_onsite')
        cls.location_blocked_sobredimensionada = cls.env.ref('wb_tech_location_blocking.location_blocked_sobredimensionada')
        cls.location_blocked_cuarentena = cls.env.ref('wb_tech_location_blocking.location_blocked_cuarentena')

    def test_01_operator_blocking_onsite(self):
        """Test blocking and unblocking with 'onsite' reason by operator user."""
        # Block
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'onsite',
            'comment': 'Test onsite block'
        })
        wizard.action_block()

        # Check location state
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_onsite.id)
        self.assertEqual(self.pos1.block_reason_type, 'onsite')
        self.assertEqual(self.pos1.original_parent_id.id, self.pasillo_a.id)

        # Check history
        history = self.env['stock.location.block.history'].search([('location_id', '=', self.pos1.id)], order='id desc', limit=1)
        self.assertEqual(history.event_type, 'block')
        self.assertEqual(history.block_reason_type, 'onsite')
        self.assertEqual(history.user_id.id, self.operator_user.id)

        # Unblock
        self.pos1.with_user(self.operator_user).action_unblock()

        # Check restored state
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos1.block_reason_type)
        self.assertFalse(self.pos1.original_parent_id)

        # Check history again
        history = self.env['stock.location.block.history'].search([('location_id', '=', self.pos1.id)], order='id desc', limit=1)
        self.assertEqual(history.event_type, 'unblock')
        self.assertEqual(history.user_id.id, self.operator_user.id)

    def test_02_onsite_block_with_pending_moves(self):
        """Test that we cannot block as 'onsite' when there are pending moves."""
        # Create a product and a pending stock move line
        product = self.env['product.product'].create({
            'name': 'Test Product 1',
            'type': 'consu',
            'is_storable': True,
        })
        
        # Create a pending move line referencing the location
        move_line = self.env['stock.move.line'].create({
            'product_id': product.id,
            'location_id': self.pos1.id,
            'location_dest_id': self.wh_stock.id,
            'quantity': 10.0,
            'state': 'assigned',
            'company_id': self.env.company.id,
            'product_uom_id': product.uom_id.id,
        })

        # Try to block
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'onsite',
            'comment': 'Test fail'
        })
        with self.assertRaises(UserError):
            wizard.action_block()

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

        # 2. Leader tries to block as no_apto WITHOUT ticket -> raises UserError
        wizard2 = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'no_apto',
            'comment': 'No ticket comment'
        })
        with self.assertRaises(UserError):
            wizard2.action_block()

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

    def test_05_onsite_and_danado_blocking(self):
        """Test blocking validations and permissions for new reasons: onsite and danado."""
        # 1. Block as Onsite (Operador can execute, goes to location_blocked_onsite)
        wizard_onsite = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'onsite',
            'comment': 'Onsite check'
        })
        wizard_onsite.action_block()
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_onsite.id)
        self.assertEqual(self.pos1.block_reason_type, 'onsite')

        # Unblock onsite
        self.pos1.with_user(self.operator_user).action_unblock()
        self.assertFalse(self.pos1.block_reason_type)

        # 2. Block as Danado (Only leader can execute, requires ticket, goes to location_blocked_danado)
        # Operator tries to block as danado -> raises error
        wizard_danado_fail = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'danado',
            'ticket': 'TICK-M1',
        })
        with self.assertRaises(UserError):
            wizard_danado_fail.action_block()

        # Leader blocks as danado
        wizard_danado = self.env['wb.stock.location.block.wizard'].with_user(self.leader_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'danado',
            'ticket': 'TICK-M2',
            'comment': 'Broken shelves'
        })
        wizard_danado.action_block()
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_danado.id)
        self.assertEqual(self.pos1.block_reason_type, 'danado')
        self.assertEqual(self.pos1.block_ticket, 'TICK-M2')

    def test_06_block_expiration_and_warning(self):
        """Test block expiration date setting and the is_block_expired compute alert field."""
        # Block with future expiration date
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'onsite',
            'expiration_date': fields.Date.from_string('2099-12-31'),
            'comment': 'Future block'
        })
        wizard.action_block()
        
        self.assertEqual(self.pos1.block_expiration_date, fields.Date.from_string('2099-12-31'))
        self.assertFalse(self.pos1.is_block_expired)

        # Unblock and re-block with past expiration date
        self.pos1.with_user(self.operator_user).action_unblock()
        
        wizard_expired = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'onsite',
            'expiration_date': fields.Date.from_string('2020-01-01'),
            'comment': 'Expired block'
        })
        wizard_expired.action_block()

        self.assertEqual(self.pos1.block_expiration_date, fields.Date.from_string('2020-01-01'))
        self.assertTrue(self.pos1.is_block_expired)

    def test_07_mass_blocking(self):
        """Test mass blocking multiple locations in a single wizard action."""
        # Block pos1 and pos2 as onsite in bulk
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id, self.pos2.id])],
            'block_reason_type': 'onsite',
            'comment': 'Bulk block test'
        })
        wizard.action_block()

        # Both should be blocked
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_onsite.id)
        self.assertEqual(self.pos2.location_id.id, self.location_blocked_onsite.id)
        self.assertEqual(self.pos1.block_reason_type, 'onsite')
        self.assertEqual(self.pos2.block_reason_type, 'onsite')

    def test_08_cuarentena_blocking_and_unblocking_validation(self):
        """Test blocking as 'cuarentena' and validating that unblocking is not allowed."""
        # Block
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'cuarentena',
            'comment': 'Test quarantine block'
        })
        wizard.action_block()

        # Check location state
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_cuarentena.id)
        self.assertEqual(self.pos1.block_reason_type, 'cuarentena')

        # Try to unblock -> raises UserError
        with self.assertRaises(UserError):
            self.pos1.with_user(self.operator_user).action_unblock()

    def test_09_sobredimensionada_blocking(self):
        """Test blocking as 'sobredimensionada' and unblocking successfully."""
        # Block
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'sobredimensionada',
            'comment': 'Test oversized block'
        })
        wizard.action_block()

        # Check location state
        self.assertEqual(self.pos1.location_id.id, self.location_blocked_sobredimensionada.id)
        self.assertEqual(self.pos1.block_reason_type, 'sobredimensionada')

        # Unblock should be allowed and restore the location parent
        self.pos1.with_user(self.operator_user).action_unblock()
        self.assertEqual(self.pos1.location_id.id, self.pasillo_a.id)
        self.assertFalse(self.pos1.block_reason_type)

    def test_10_cuarentena_robust_unblocking_validation(self):
        """Test robust quarantine check for unblocking (e.g. if reason text contains cuarentena or parent is Cuarentena)."""
        # Block with reason_type onsite but comment containing 'cuarentena'
        wizard = self.env['wb.stock.location.block.wizard'].with_user(self.operator_user).create({
            'location_ids': [(6, 0, [self.pos1.id])],
            'block_reason_type': 'onsite',
            'comment': 'Puesto en cuarentena temporal'
        })
        wizard.action_block()

        # Try to unblock -> raises UserError because comment has 'cuarentena'
        with self.assertRaises(UserError):
            self.pos1.with_user(self.operator_user).action_unblock()

        # Unblock by overriding reason to test the other condition (parent location containing 'cuarentena')
        self.pos1.sudo().write({
            'block_reason': 'No comment',
            'location_id': self.location_blocked_cuarentena.id,
        })
        # Try to unblock -> raises UserError because parent is a Cuarentena location
        with self.assertRaises(UserError):
            self.pos1.with_user(self.operator_user).action_unblock()

