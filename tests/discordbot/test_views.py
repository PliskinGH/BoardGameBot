"""Tests for the private move panels and their custom ids."""

import asyncio

import discord
from django.test import (SimpleTestCase, TestCase, TransactionTestCase,
                         override_settings)

from discordbot import errors, views
from games.models import MatchStatus
from games.services import matches
from games.engine.base import ActionOption, Param, RenderModel
from games.services.errors import UndoForbidden
from tests.discordbot.fakes import (bot_match, discord_player,
                                    interaction_for, mark_hand, setup_match)
from tests.factories import play_first, started_match
from tests.support import NoDiscordMixin

# The largest pk a bigint column can hold.
MAX_PK = 9223372036854775807
NONCE = 'abcdef'
MODAL_NONCE = '123456'


class CustomIdTests(NoDiscordMixin, SimpleTestCase):
    def test_every_id_stays_far_below_the_limit(self):
        token = 'a' * 12
        ids = [views.board_id(MAX_PK, 'act'),
               views.board_id(MAX_PK, 'hand'),
               views.board_id(MAX_PK, 'undo'),
               views.panel_id(MAX_PK, token, NONCE, 'do', 999),
               views.panel_id(MAX_PK, token, NONCE, 'pick', 999, 999),
               views.panel_id(MAX_PK, token, NONCE, 'form', 999)]

        for custom_id in ids:
            with self.subTest(custom_id=custom_id):
                self.assertLessEqual(len(custom_id), 64)
                self.assertLessEqual(len(custom_id), views.ID_LIMIT)

    def test_a_panel_opening_nonce_separates_simultaneous_panels(self):
        token = 'a' * 12

        self.assertNotEqual(
            views.panel_id(1, token, NONCE, 'do', 0),
            views.panel_id(1, token, '123456', 'do', 0))
        self.assertNotEqual(
            views.panel_id(1, token, NONCE, 'modal', 0, MODAL_NONCE),
            views.panel_id(1, token, NONCE, 'modal', 0, '654321'))

    def test_an_oversized_id_is_refused_before_it_is_sent(self):
        with self.assertRaises(ValueError):
            views._checked('x' * (views.ID_LIMIT + 1))


class ParamModalTests(NoDiscordMixin, SimpleTestCase):
    def test_every_parameter_gets_a_label(self):
        option = ActionOption(
            id='trade', label='Trade',
            params=(Param('a', 'First', options=('1',)),
                    Param('b', 'Second', options=('2',))))

        modal = views.ParamModal(1, 'a' * 12, NONCE, MODAL_NONCE, 0, option,
                            RenderModel())
        labels = [item for item in modal.walk_children()
                  if isinstance(item, discord.ui.Label)]

        self.assertEqual([label.text for label in labels],
                         ['First', 'Second'])


class TokenTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match()

    def _token(self, match, player):
        model = views.render_model(match, player)
        position = views.viewer_position(match, player)
        return views.panel_token(match, model, position)

    def test_the_token_is_stable_for_one_state(self):
        player = self.match.active_seat.player

        self.assertEqual(self._token(self.match, player),
                         self._token(self.match, player))

    def test_the_token_changes_when_the_table_moves(self):
        player = self.match.active_seat.player
        before = self._token(self.match, player)

        match = play_first(self.match, player)

        self.assertNotEqual(before, self._token(match, player))

    def test_each_seat_has_its_own_token(self):
        self.assertNotEqual(self._token(self.match, self.players[0]),
                            self._token(self.match, self.players[1]))


@override_settings(WEB_BASE_URL='https://example.test')
class PanelTests(NoDiscordMixin, TransactionTestCase):
    def setUp(self):
        self.match, self.players = bot_match()

    def test_the_active_player_gets_a_panel(self):
        player = self.match.active_seat.player
        interaction = interaction_for(player, self.match)

        asyncio.run(views.open_panel(interaction, self.match.pk))

        [message] = interaction.response.messages
        view = message['view']
        text = '\n'.join(item.content for item in view.walk_children()
                          if isinstance(item, discord.ui.TextDisplay))
        self.assertIn('Your hand', text)
        self.assertIsInstance(view, discord.ui.LayoutView)

    def test_the_panel_labels_its_action_and_parameter(self):
        player = self.match.active_seat.player
        position = views.viewer_position(self.match, player)
        model = views.render_model(self.match, player)

        view = views.panel_view(self.match, model,
                                views.panel_token(self.match, model, position), NONCE)
        text = '\n'.join(item.content for item in view.walk_children()
                          if isinstance(item, discord.ui.TextDisplay))
        row = next(item for item in view.walk_children()
                   if isinstance(item, discord.ui.ActionRow))
        select = next(item for item in row.children
                      if isinstance(item, views.MatchParamSelect))

        self.assertIn('Play a card', text)
        self.assertEqual(select.item.placeholder, 'Card')

    def test_a_seat_whose_turn_it_is_not_is_told_so(self):
        interaction = interaction_for(self.players[1], self.match)

        asyncio.run(views.open_panel(interaction, self.match.pk))

        self.assertIn('not your turn',
                      interaction.response.messages[0]['content'])

    def test_grid_actions_are_labelled_and_cells_are_numbered(self):
        match, _players = started_match(slug='grid-sample-game')
        player = match.active_seat.player
        position = views.viewer_position(match, player)
        model = views.render_model(match, player)

        view = views.panel_view(match, model,
                                views.panel_token(match, model, position), NONCE)
        text = '\n'.join(item.content for item in view.walk_children()
                          if isinstance(item, discord.ui.TextDisplay))
        selects = [item for row in view.walk_children()
                   if isinstance(row, discord.ui.ActionRow)
                   for item in row.children
                   if isinstance(item, views.MatchParamSelect)]

        self.assertIn('Move', text)
        self.assertIn('Scout', text)
        self.assertEqual(selects[0].item.placeholder, 'Cell')
        self.assertTrue(selects[0].item.options[0].label.startswith('Column: '))

    def test_a_player_without_a_seat_is_told_so(self):
        outsider = discord_player(44, 'user44')
        interaction = interaction_for(outsider, self.match)

        asyncio.run(views.open_panel(interaction, self.match.pk))

        self.assertIn('no seat',
                      interaction.response.messages[0]['content'])

    def test_a_finished_match_has_no_panel(self):
        matches.close_match(self.match.pk, self.players[0])
        interaction = interaction_for(self.players[0], self.match)

        asyncio.run(views.open_panel(interaction, self.match.pk))

        self.assertIn('not being played',
                      interaction.response.messages[0]['content'])

    def test_the_hand_panel_keeps_the_other_hands_out(self):
        mark_hand(self.match, 0, 'ZEBRA')
        mark_hand(self.match, 1, 'UNICORN')
        interaction = interaction_for(self.players[0], self.match)

        asyncio.run(views.show_hand(interaction, self.match.pk))

        [message] = interaction.response.messages
        self.assertIn('ZEBRA', message['embed'].description)
        self.assertNotIn('UNICORN', message['embed'].description)



class BoardViewTests(NoDiscordMixin, TestCase):
    def test_a_setup_board_offers_join_leave_start_and_close(self):
        match, _host, _guest = setup_match()

        labels = [item.item.label for item in views.board_view(match).children]

        self.assertEqual(labels, ['Join', 'Leave', 'Start', 'Close'])

    def test_an_active_board_offers_a_turn_private_info_and_close(self):
        match, _players = bot_match()

        labels = [item.item.label for item in views.board_view(match).children]

        self.assertIn('Take a turn', labels)
        self.assertIn('Private info', labels)
        self.assertIn('Close', labels)
        self.assertNotIn('Join', labels)

    def test_a_game_without_private_info_has_no_private_button(self):
        match, _players = started_match(slug='grid-sample-game')

        labels = [item.item.label for item in views.board_view(match).children]

        self.assertNotIn('Private info', labels)


class BoardButtonTests(NoDiscordMixin, TransactionTestCase):
    def test_the_join_button_seats_the_caller_with_their_server_name(self):
        match, _host, guest = setup_match()
        interaction = interaction_for(guest, match, display_name='Guest name')

        asyncio.run(views.join_match(interaction, match.pk))

        seat = match.seats.get(position=1)
        self.assertEqual(seat.player, guest)
        self.assertEqual(seat.display_name, 'Guest name')
        self.assertIn('Seat 2', interaction.response.messages[0]['content'])

    def test_the_start_button_starts_the_match(self):
        match, host, guest = setup_match()
        matches.join_match(match.pk, guest)
        interaction = interaction_for(host, match, display_name='Host name')

        asyncio.run(views.start_match(interaction, match.pk))

        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.ACTIVE)
        self.assertIn('started', interaction.response.messages[0]['content'])

    def test_the_close_button_closes_the_match(self):
        match, host, _guest = setup_match()
        interaction = interaction_for(host, match)

        asyncio.run(views.close_match(interaction, match.pk))

        match.refresh_from_db()
        self.assertEqual(match.status, MatchStatus.FINISHED)
        self.assertIn('closed', interaction.response.messages[0]['content'])

@override_settings(WEB_BASE_URL='https://example.test')
class ApplyChoiceTests(NoDiscordMixin, TransactionTestCase):
    def setUp(self):
        self.match, self.players = bot_match()
        self.player = self.match.active_seat.player

    def _token(self):
        model = views.render_model(self.match, self.player)
        return views.panel_token(
            self.match, model,
            views.viewer_position(self.match, self.player))

    def test_a_pick_applies_the_chosen_card(self):
        token = self._token()
        interaction = interaction_for(self.player, self.match)

        asyncio.run(views.apply_choice(interaction, self.match.pk, token, NONCE,
                                       0, {0: 0}))

        self.match.refresh_from_db()
        self.assertEqual(self.match.version, 1)
        self.assertTrue(interaction.response.edits)

    def test_a_stale_panel_is_refused(self):
        token = self._token()
        play_first(self.match, self.player)
        interaction = interaction_for(self.player, self.match)

        asyncio.run(views.apply_choice(interaction, self.match.pk, token, NONCE,
                                       0, {0: 0}))

        self.match.refresh_from_db()
        self.assertEqual(self.match.version, 1)
        self.assertIn('out of date',
                      interaction.response.messages[0]['content'])

    def test_a_forged_action_index_is_refused(self):
        token = self._token()
        interaction = interaction_for(self.player, self.match)

        asyncio.run(views.apply_choice(interaction, self.match.pk, token, NONCE,
                                       99, {}))

        self.match.refresh_from_db()
        self.assertEqual(self.match.version, 0)
        self.assertIn('out of date',
                      interaction.response.messages[0]['content'])

    def test_a_forged_option_index_is_refused(self):
        token = self._token()
        interaction = interaction_for(self.player, self.match)

        asyncio.run(views.apply_choice(interaction, self.match.pk, token, NONCE,
                                       0, {0: 99}))

        self.match.refresh_from_db()
        self.assertEqual(self.match.version, 0)

    def test_another_player_cannot_use_the_panel(self):
        token = self._token()
        interaction = interaction_for(self.players[1], self.match)

        asyncio.run(views.apply_choice(interaction, self.match.pk, token, NONCE,
                                       0, {0: 0}))

        self.match.refresh_from_db()
        self.assertEqual(self.match.version, 0)
        self.assertIn('out of date',
                      interaction.response.messages[0]['content'])


class UndoTextTests(NoDiscordMixin, SimpleTestCase):
    def test_every_undo_refusal_is_explained(self):
        cases = {'revealed': 'only a host', 'random': 'randomness',
                 'upgrade': 'upgrade', 'other': 'cannot be undone'}

        for reason, fragment in cases.items():
            with self.subTest(reason=reason):
                self.assertIn(fragment,
                              errors.refusal_text(UndoForbidden(reason)))


class UndoPanelTests(NoDiscordMixin, TransactionTestCase):
    def test_undoing_a_reveal_is_refused(self):
        match, _players = bot_match()
        player = match.active_seat.player
        play_first(match, player)
        interaction = interaction_for(player, match)

        asyncio.run(views.undo_match(interaction, match.pk))

        self.assertIn('only a host',
                      interaction.response.messages[0]['content'])

    def test_a_pass_is_undone(self):
        match, _players = bot_match()
        seat = match.seats.get(position=0)
        seat.private_state = {**seat.private_state, 'hand': []}
        seat.save(update_fields=['private_state'])
        player = match.active_seat.player
        play_first(match, player)
        interaction = interaction_for(player, match)

        asyncio.run(views.undo_match(interaction, match.pk))

        self.assertIn('Undone', interaction.response.messages[0]['content'])



class ParameterOptionTests(NoDiscordMixin, TransactionTestCase):
    def test_card_options_are_labelled_from_the_hand(self):
        match, players = bot_match()
        player = match.active_seat.player
        model = views.render_model(match, player)
        param = model.actions[0].params[0]

        options = views.parameter_options(model, param)

        hand = next(zone for zone in model.zones if zone.kind == 'hand')
        self.assertEqual([option.value for option in options],
                         [str(index) for index in range(len(param.options))])
        self.assertEqual([option.label for option in options],
                         [card.label for card in hand.cards])

    def test_seat_options_are_labelled_from_the_seats(self):
        match, players = bot_match()
        seat = match.seats.get(position=0)
        seat.private_state = {
            **seat.private_state,
            'hand': [{'id': 'swap', 'label': 'Swap', 'value': 0},
                     *seat.private_state['hand']],
        }
        seat.save(update_fields=['private_state'])
        player = match.active_seat.player
        play_first(match, player)
        model = views.render_model(match, player)
        param = model.actions[0].params[0]

        options = views.parameter_options(model, param)

        others = [seat.label for seat in model.seats if seat.position != 0]
        self.assertEqual([option.label for option in options], others)


@override_settings(WEB_BASE_URL='https://example.test')
class EndToEndTests(NoDiscordMixin, TransactionTestCase):
    def test_a_whole_match_is_played_from_the_panels(self):
        match, players = bot_match()

        for _step in range(200):
            match.refresh_from_db()
            if match.status != MatchStatus.ACTIVE:
                break
            player = match.active_seat.player
            model = views.render_model(match, player)
            token = views.panel_token(
                match, model, views.viewer_position(match, player))
            option = model.actions[0]
            values = {index: 0 for index, _param in enumerate(option.params)}
            interaction = interaction_for(player, match)

            asyncio.run(views.apply_choice(interaction, match.pk, token, NONCE, 0,
                                           values))
        else:
            self.fail('The match did not finish.')

        self.assertEqual(match.status, MatchStatus.FINISHED)

