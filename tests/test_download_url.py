from src.utils.download_url import normalize_download_url


def test_normalize_download_url_rewrites_known_cloudfront_host() -> None:
    value = "https://d3j85m1nd79zoa.cloudfront.net/950331075322.pdf"
    assert normalize_download_url(value) == "https://eplacement-2.s3.ap-southeast-5.amazonaws.com/950331075322.pdf"


def test_normalize_download_url_keeps_regular_s3_url() -> None:
    value = "https://eplacement-2.s3.ap-southeast-5.amazonaws.com/950331075322.pdf"
    assert normalize_download_url(value) == value


def test_normalize_download_url_rejects_blank_values() -> None:
    assert normalize_download_url("Tiada Maklumat") is None
