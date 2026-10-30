"""Regression tests for the Gemini 400 INVALID_ARGUMENT on tool declarations.

The Gemini API requires ARRAY parameters to carry `items` and OBJECT
parameters to carry `properties`. Bare python `list`/`dict` annotations used to
produce declarations without them, breaking EVERY Gemini call once any of the
affected tools (zip_files, save_extracted_document, http_request) was in the
catalog. Covers both execution paths: the legacy gemini_tool_declarations and
the LangChain stack (StructuredTool args_schema -> langchain-google-genai).
"""
import sys
import os
import unittest

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.genai import types
from langchain_google_genai._function_utils import (
    convert_to_genai_function_declarations,
)

from agent.lc.tools_lc import build_lc_tools, gemini_tool_declarations
from tools import AVAILABLE_TOOLS
from tools.archive_tools import zip_files
from tools.http_request import http_request
from tools.linux.document_saver import save_extracted_document


def _assert_genai_schema_valid(schema, where=""):
    """ARRAY must have items; OBJECT must have properties (recursively)."""
    if schema is None:
        return
    if schema.type == types.Type.ARRAY and schema.items is None:
        raise AssertionError(f"{where}: ARRAY parameter without items")
    if schema.type == types.Type.OBJECT and schema.properties is None:
        raise AssertionError(f"{where}: OBJECT parameter without properties")
    for name, child in (schema.properties or {}).items():
        _assert_genai_schema_valid(child, f"{where}.{name}")
    if schema.items is not None:
        _assert_genai_schema_valid(schema.items, f"{where}[]")


def _each_param(declarations):
    for tool in declarations:
        for decl in tool.function_declarations:
            for name, prop in (decl.parameters.properties or {}).items():
                yield f"{decl.name}.{name}", prop


def _params_of(declarations):
    """Property map of the FIRST declaration (single-tool lookups)."""
    decl = declarations[0].function_declarations[0]
    return dict(decl.parameters.properties or {})


class TestLegacyGeminiDeclarations(unittest.TestCase):
    def test_every_catalog_tool_produces_valid_declaration(self):
        for func in AVAILABLE_TOOLS:
            decls = gemini_tool_declarations([func])
            for name, prop in _each_param(decls):
                if prop.type == types.Type.ARRAY:
                    self.assertIsNotNone(prop.items, f"{name}: ARRAY without items")
                if prop.type == types.Type.OBJECT:
                    self.assertIsNotNone(prop.properties, f"{name}: OBJECT without properties")

    def test_zip_files_array_has_items(self):
        prop = _params_of(gemini_tool_declarations([zip_files]))["file_paths"]
        self.assertEqual(prop.type, types.Type.ARRAY)
        self.assertEqual(prop.items.type, types.Type.STRING)


class TestLangChainGeminiPath(unittest.TestCase):
    def test_gemini_safe_conversion_has_no_invalid_schemas(self):
        lc = build_lc_tools(AVAILABLE_TOOLS, gemini_safe=True)
        decls = convert_to_genai_function_declarations(lc)
        for name, prop in _each_param(decls):
            if prop.type == types.Type.ARRAY:
                self.assertIsNotNone(prop.items, f"{name}: ARRAY without items")
            # dict params are declared as STRING in gemini_safe mode, so no
            # OBJECT can reach the API without properties.
            if prop.type == types.Type.OBJECT:
                self.assertIsNotNone(prop.properties, f"{name}: OBJECT without properties")

    def test_gemini_safe_turns_dict_params_into_json_strings(self):
        lc = build_lc_tools([http_request], gemini_safe=True)
        prop = _params_of(convert_to_genai_function_declarations(lc))["headers"]
        self.assertEqual(prop.type, types.Type.STRING)
        self.assertIn("JSON object", prop.description)

    def test_non_gemini_providers_keep_object_type(self):
        lc = build_lc_tools([http_request])
        prop = _params_of(convert_to_genai_function_declarations(lc))["headers"]
        self.assertEqual(prop.type, types.Type.OBJECT)

    def test_zip_files_lc_gemini_safe_has_items(self):
        lc = build_lc_tools([zip_files], gemini_safe=True)
        prop = _params_of(convert_to_genai_function_declarations(lc))["file_paths"]
        self.assertEqual(prop.type, types.Type.ARRAY)
        self.assertIsNotNone(prop.items)


class TestDictParamNormalization(unittest.TestCase):
    """Tools accept both a real object and a JSON-encoded string."""

    @pytest.fixture(autouse=True)
    def _init_test_db(self, mock_db_path):
        import database

        database.init_db()
        # http_request gates on PERM_WEB_SEARCH before anything else; a fresh
        # test DB has it disabled, which would mask the normalization path.
        database.set_config("PERM_WEB_SEARCH", "true")

    def test_http_request_rejects_invalid_headers_json_before_network(self):
        result = http_request("https://example.com", headers="{oops")
        self.assertIn("Error", result)
        self.assertIn("headers", result)

    def test_save_extracted_document_rejects_invalid_extracted_data_json(self):
        result = save_extracted_document(category="invoice", extracted_data="{oops")
        self.assertIn("Error", result)
        self.assertIn("extracted_data", result)

    def test_save_extracted_document_accepts_json_string(self):
        # Normalization path: string -> dict. The function then proceeds to the
        # DB lookup; assert it did NOT fail on the argument itself by mocking
        # the DB boundary with an unexpected-but-harmless failure.
        from unittest.mock import patch

        with patch("tools.linux.document_saver.get_db", side_effect=RuntimeError("stop")):
            try:
                result = save_extracted_document(
                    category="invoice", extracted_data='{"total": "R$10"}'
                )
            except RuntimeError:
                self.fail("string extracted_data was not normalized to a dict")
        self.assertNotIn("must be a JSON object", result)


if __name__ == "__main__":
    unittest.main()