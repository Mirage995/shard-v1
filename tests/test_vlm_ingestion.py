from unittest.mock import patch

from backend.vlm_ingestion import describe_images


def test_describe_images_uses_ollama_when_available():
    with patch("backend.vlm_ingestion._call_ollama", return_value=("Objects/Entities:\nchart", "ollama:qwen2.5vl:3b")) as ollama:
        with patch("backend.vlm_ingestion._call_openrouter") as openrouter:
            result = describe_images(["C:/tmp/chart.png"], "paper charts")

    assert "[VISUAL EVIDENCE]" in result
    assert "Image 1 (C:/tmp/chart.png):" in result
    assert "source: visual_ingestion" in result
    assert "image_path: C:/tmp/chart.png" in result
    assert "provider: ollama:qwen2.5vl:3b" in result
    assert "error: false" in result
    assert "Objects/Entities:\nchart" in result
    ollama.assert_called_once_with("C:/tmp/chart.png", "paper charts")
    openrouter.assert_not_called()


def test_describe_images_falls_back_to_openrouter_when_ollama_fails():
    with patch("backend.vlm_ingestion._call_ollama", side_effect=RuntimeError("down")) as ollama:
        with patch(
            "backend.vlm_ingestion._call_openrouter",
            return_value=("Objects/Entities:\ndiagram", "openrouter:qwen/qwen-2.5-vl-7b-instruct:free"),
        ) as openrouter:
            result = describe_images(["C:/tmp/diagram.png"], "paper diagrams")

    assert "provider: openrouter:qwen/qwen-2.5-vl-7b-instruct:free" in result
    assert "error: false" in result
    assert "Objects/Entities:\ndiagram" in result
    ollama.assert_called_once_with("C:/tmp/diagram.png", "paper diagrams")
    openrouter.assert_called_once_with("C:/tmp/diagram.png", "paper diagrams")


def test_describe_images_with_empty_list_returns_empty_string():
    with patch("backend.vlm_ingestion._call_ollama") as ollama:
        with patch("backend.vlm_ingestion._call_openrouter") as openrouter:
            result = describe_images([], "anything")

    assert result == ""
    ollama.assert_not_called()
    openrouter.assert_not_called()


def test_describe_images_marks_error_block_when_all_providers_fail():
    with patch("backend.vlm_ingestion._call_ollama", side_effect=RuntimeError("down")):
        with patch("backend.vlm_ingestion._call_openrouter", side_effect=RuntimeError("down too")):
            result = describe_images(["C:/tmp/bad.png"], "paper figures")

    assert "source: visual_ingestion" in result
    assert "image_path: C:/tmp/bad.png" in result
    assert "provider: unavailable" in result
    assert "error: true" in result
    assert "insufficient evidence due to provider failure" in result
