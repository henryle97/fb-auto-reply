import pytest

from fb_auto_reply.facebook import parse_post_ref

PAGE = "100000000000001"


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("100000000000001_300000000000003", "100000000000001_300000000000003"),
        (" 300000000000003 ", "100000000000001_300000000000003"),
        (
            "https://www.facebook.com/100000000000009/posts/300000000000003",
            "100000000000001_300000000000003",
        ),
        (
            "https://www.facebook.com/100000000000009/posts/300000000000005?substory_index=1",
            "100000000000001_300000000000005",
        ),
        ("facebook.com/examplepage/posts/300000000000003/", "100000000000001_300000000000003"),
        (
            "https://m.facebook.com/permalink.php?story_fbid=300000000000003&id=100000000000001",
            "100000000000001_300000000000003",
        ),
    ],
)
def test_parse_post_ref(ref, expected):
    assert parse_post_ref(ref, PAGE) == expected


@pytest.mark.parametrize(
    ("ref", "error"),
    [
        ("https://www.facebook.com/examplepage/posts/pfbid02abcXYZ", "pfbid"),
        ("https://www.facebook.com/examplepage", "no post id"),
        ("https://example.com/posts/123", "expected a post id"),
        ("abc", "expected a post id"),
    ],
)
def test_parse_post_ref_rejects(ref, error):
    with pytest.raises(ValueError, match=error):
        parse_post_ref(ref, PAGE)


async def test_network_error_becomes_facebook_error():
    import httpx

    from fb_auto_reply.facebook import FacebookError, GraphClient

    def boom(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    client = GraphClient("t", "v25.0", httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    with pytest.raises(FacebookError, match="ConnectTimeout"):
        await client.reply_comment("c1", "hi")
    assert await client.get_post_text("p1") == ""  # post context is optional
    await client.aclose()
