from article_metadata import extract_metadata


def test_article_author_is_matched_by_url_not_first_comment():
    html='<a class="user-name" href="/123">评论用户</a><a href="/1064583172">老鬼的逻辑</a>'
    assert extract_metadata(html,'https://xueqiu.com/1064583172/169264119')['author_name']=='老鬼的逻辑'
    assert extract_metadata('<a class="user-name" href="/123">评论用户</a>','https://xueqiu.com/1064583172/169264119')['author_name'] is None


def test_wechat_metadata_unchanged():
    assert extract_metadata('<span id="js_name">公众号</span>','https://mp.weixin.qq.com/s/a')['author_name']=='公众号'
