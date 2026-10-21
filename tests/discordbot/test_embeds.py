"""Tests for the embeds the bot posts."""

import discord
from django.test import SimpleTestCase, TestCase

from discordbot import embeds
from games.services.projections import render_model
from tests.discordbot.fakes import bot_match, mark_hand


def embed_text(embed: discord.Embed) -> str:
    """Return every text an embed displays."""
    parts = [embed.title or '', embed.description or '']
    footer = embed.footer
    if footer is not None:
        text = footer.text
        if text:
            parts.append(text)
    parts.extend((field.name or '') + (field.value or '')
                 for field in embed.fields)
    return ' '.join(parts)


class BoardEmbedTests(TestCase):
    def setUp(self):
        self.match, _players = bot_match()

    def test_the_public_board_keeps_the_hands_out(self):
        mark_hand(self.match, 0, 'ZEBRA')

        embed = embeds.board_embed(
            self.match, render_model(self.match, None), 'Card Sample Game',
            web_url='https://example.test/g/1/matches/1/')

        text = embed_text(embed)
        self.assertNotIn('ZEBRA', text)
        self.assertIn('Seats', text)
        self.assertEqual(embed.url, 'https://example.test/g/1/matches/1/')

    def test_the_title_uses_the_match_name(self):
        self.match.name = 'Friday table'
        self.match.save(update_fields=['name'])

        embed = embeds.board_embed(
            self.match, render_model(self.match, None), 'Card Sample Game')

        self.assertIn('Card Sample Game: Friday table', embed.title)

    def test_the_footer_uses_the_rules_version(self):
        self.match.version = 7
        self.match.rules_version = 3
        self.match.save(update_fields=['version', 'rules_version'])

        embed = embeds.board_embed(
            self.match, render_model(self.match, None), 'Card Sample Game')

        self.assertIn('rules v3', embed.footer.text)
        self.assertNotIn('rules v7', embed.footer.text)

    def test_the_private_embed_is_generic_and_hides_other_hands(self):
        mark_hand(self.match, 0, 'ZEBRA')
        mark_hand(self.match, 1, 'UNICORN')
        player = self.match.seats.get(position=0).player

        embed = embeds.private_embed(
            self.match, render_model(self.match, player), 'Card Sample Game')
        text = embed_text(embed)

        self.assertIn('private info', embed.title)
        self.assertIn('ZEBRA', text)
        self.assertNotIn('UNICORN', text)
        self.assertNotIn('—', text)
        self.assertNotIn('·', text)

    def test_the_recap_lists_the_scores(self):
        embed = embeds.recap_embed(
            self.match, {'scores': [{'name': 'Wendy', 'coins': 3}]},
            'Card Sample Game')

        self.assertIn('Game over.', embed.description)
        self.assertIn('Wendy', embed.fields[0].value)
        self.assertIn('coins', embed.fields[0].value)

    def test_the_hand_shows_the_callers_cards(self):
        mark_hand(self.match, 0, 'ZEBRA')
        player = self.match.seats.get(position=0).player

        embed = embeds.hand_embed(self.match,
                                  render_model(self.match, player), 'Card Sample Game')

        self.assertIn('ZEBRA', embed.description)
        self.assertIn('Your hand', embed.description)


class FitTests(SimpleTestCase):
    def test_an_oversized_embed_is_trimmed(self):
        embed = discord.Embed(title='t' * 500, description='d' * 5000)
        for _index in range(30):
            embed.add_field(name='n' * 300, value='v' * 2000)

        embeds.fit(embed)

        self.assertLessEqual(len(embed.fields), embeds.FIELD_LIMIT)
        for field in embed.fields:
            self.assertLessEqual(len(field.name or ''),
                                 embeds.FIELD_NAME_LIMIT)
            self.assertLessEqual(len(field.value or ''),
                                 embeds.FIELD_VALUE_LIMIT)

    def test_a_long_line_is_clipped(self):
        self.assertEqual(len(embeds.clip('x' * 100, 10)), 10)
        self.assertTrue(embeds.clip('x' * 100, 10).endswith('...'))
