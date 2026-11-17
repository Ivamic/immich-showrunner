# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artwork for shows and seasons, made from frames of the album's videos.

A style is a folder with a declarative `style.yaml`, its fonts and its assets. The renderer
turns a style, a few frames and a title into the pictures a media server shows: the poster,
the landscape picture, the backdrop and the logo of a show, and the poster of a season.
No code runs from a style, and the same input always gives the same bytes."""
