"""The Failed message must name the cause, not ffmpeg's generic wrap-up lines."""
import converter as c

# Real ffmpeg 8.1 stderr: libopus refusing TV-style 5.1(side) audio.
OPUS_FAIL = """\
[libopus @ 0000028b69a7ee40] Invalid channel layout 5.1(side) for specified mapping family -1.
[aost#0:0/libopus @ 0000028b67af6a40] [enc:libopus @ 0000028b67b768c0] Error while opening encoder - maybe incorrect parameters such as bit_rate, rate, width or height.
[af#0:0 @ 0000028b69b331c0] Error sending frames to consumers: Invalid argument
[af#0:0 @ 0000028b69b331c0] Task finished with error code: -22 (Invalid argument)
[af#0:0 @ 0000028b69b331c0] Terminating thread with return code -22 (Invalid argument)
[aost#0:0/libopus @ 0000028b67af6a40] [enc:libopus @ 0000028b67b768c0] Could not open encoder before EOF
[aost#0:0/libopus @ 0000028b67af6a40] Task finished with error code: -22 (Invalid argument)
[aost#0:0/libopus @ 0000028b67af6a40] Terminating thread with return code -22 (Invalid argument)
[out#0/opus @ 0000028b67af5540] Nothing was written into output file, because at least one of its streams received no packets.
"""


def test_extract_error_skips_ffmpeg_wrap_up_lines():
    assert c.extract_error(OPUS_FAIL) == \
        "Invalid channel layout 5.1(side) for specified mapping family -1."


def test_extract_error_still_returns_a_plain_last_error():
    assert c.extract_error("x.ts: No such file or directory\n") == \
        "x.ts: No such file or directory"
