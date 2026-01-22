from ondepi.azuracast import format_song


def test_format_song():
    assert format_song("Artist", "Track") == "Artist - Track"
    assert format_song("Artist", "") == "Artist"
    assert format_song("", "Track") == "Track"
    assert format_song("", "") == "Live"
