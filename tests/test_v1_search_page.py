from bhka.v1.search_page import SearchPageCandidateParser, canonical_video_id


def test_canonical_video_id_accepts_page_output_variants():
    assert canonical_video_id("//www.bilibili.com/video/BV1AbCdEf123?p=2") == "BV1AbCdEf123"
    assert canonical_video_id("https://www.bilibili.com/video/av123456") == "av123456"
    assert canonical_video_id("/video/123456") == "av123456"
    assert canonical_video_id("https://example.com/not-video") is None


def test_search_page_parser_collects_all_video_anchors_and_deduplicates():
    html = """
    <main>
      <a href="//www.bilibili.com/video/BV1AbCdEf123?p=1">稍后再看3394102:57</a>
      <a href="https://www.bilibili.com/video/av123456">开源工程讲解</a>
      <a href="/video/BV1AbCdEf123?spm_id_from=search" title="STM32 PCB 入门">
        重复卡片
      </a>
      <a href="https://space.bilibili.com/42">UP 主页面</a>
    </main>
    """

    candidates = SearchPageCandidateParser().parse(html, query="STM32 PCB")

    assert [candidate.canonical_id for candidate in candidates] == ["BV1AbCdEf123", "av123456"]
    assert candidates[0].title == "STM32 PCB 入门"
    assert candidates[0].url == "https://www.bilibili.com/video/BV1AbCdEf123"
    assert candidates[0].provenance == ["bilibili_search_page"]
    assert candidates[0].matched_queries == ["STM32 PCB"]


def test_search_page_parser_tolerates_empty_and_malformed_markup():
    parser = SearchPageCandidateParser()

    assert parser.parse("", query="test") == []
    assert parser.parse('<a href="[bad">bad</a>', query="test") == []
