from unittest.mock import patch

from backend.vlm_ingestion import OPENROUTER_RETRIES, describe_images


def test_describe_images_uses_openrouter_when_available():
    with patch(
        "backend.vlm_ingestion._call_openrouter",
        return_value=("Objects/Entities:\nchart", "openrouter:qwen/qwen-2.5-vl-7b-instruct:free"),
    ) as openrouter:
        with patch("backend.vlm_ingestion._call_ollama") as ollama:
            result = describe_images(["C:/tmp/chart.png"], "paper charts")

    assert "[VISUAL EVIDENCE]" in result
    assert "Image 1 (C:/tmp/chart.png):" in result
    assert "source: visual_ingestion" in result
    assert "image_path: C:/tmp/chart.png" in result
    assert "provider: openrouter:qwen/qwen-2.5-vl-7b-instruct:free" in result
    assert "error: false" in result
    assert "Objects/Entities:\nchart" in result
    openrouter.assert_called_once_with("C:/tmp/chart.png", "paper charts")
    ollama.assert_not_called()


def test_describe_images_falls_back_to_ollama_when_openrouter_fails():
    with patch("backend.vlm_ingestion._call_openrouter", side_effect=RuntimeError("down")) as openrouter:
        with patch(
            "backend.vlm_ingestion._call_ollama",
            return_value=("Objects/Entities:\ndiagram", "ollama:qwen2.5vl:3b"),
        ) as ollama:
            result = describe_images(["C:/tmp/diagram.png"], "paper diagrams")

    assert "provider: ollama:qwen2.5vl:3b" in result
    assert "error: false" in result
    assert "Objects/Entities:\ndiagram" in result
    ollama.assert_called_once_with("C:/tmp/diagram.png", "paper diagrams")


def test_describe_images_with_empty_list_returns_empty_string():
    with patch("backend.vlm_ingestion._call_openrouter") as openrouter:
        with patch("backend.vlm_ingestion._call_ollama") as ollama:
            result = describe_images([], "anything")

    assert result == ""
    openrouter.assert_not_called()
    ollama.assert_not_called()


def test_describe_images_marks_error_block_when_all_providers_fail():
    with patch("backend.vlm_ingestion._call_openrouter", side_effect=RuntimeError("down")) as openrouter:
        with patch("backend.vlm_ingestion._call_ollama", side_effect=RuntimeError("down too")):
            result = describe_images(["C:/tmp/bad.png"], "paper figures")

    assert "source: visual_ingestion" in result
    assert "image_path: C:/tmp/bad.png" in result
    assert "provider: unavailable" in result
    assert "error: true" in result
    assert "insufficient evidence due to provider failure" in result
