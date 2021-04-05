#!/usr/bin/env python
"""
A python library for CRC calculation

Copyright 2021 Garden Tools software

crcengine is free software: you can redistribute it an d /or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

crcengine is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with crcengine.  If not, see <https://www.gnu.org/licenses/>.
"""
from __future__ import generator_stop
from collections import namedtuple
import os
import pathlib
import textwrap

from jinja2 import Environment, FileSystemLoader

from .algorithms import get_algorithm_params
from .calc import create_lsb_table, create_msb_table
from .version import __version__ as crcengine_version

# Generated file information
_GenFile = namedtuple("GenFile", ["template", "output"])


def generate_code(
    crc_params, output_dir="out/", language="C", seed_parameter=False, func_name=None
):
    """Generate code implementing a specific CRC. Currently only language=C is
    supported"""
    if isinstance(crc_params, str):
        # crc_params is an algorithm name, so replace it with the parameters
        crc_params = get_algorithm_params(crc_params)

    env = _get_jinja_environment()
    template_params = _get_template_params(
        crc_params, output_dir, seed_parameter, func_name, language
    )
    _generate_output_files(env, template_params)


def _get_template_params(crc_params, output_dir, seed_parameter, func_name, language):
    datatype_bits = _get_datatype_bits(crc_params["width"])
    crc_id = crc_params["name"].replace("-", "_")
    if not func_name:
        func_name = crc_id
    template_params = {
        "after_table": "",
        "crc_datatype": "uint{datatype_bits}_t".format(datatype_bits=datatype_bits),
        "comment_begin": "/*",
        "comment_end": "*/",
        "datatype_bits": datatype_bits,
        "before_table": "",
        "byte_type": "uint8_t",
        "function_name": func_name,
        "language": language,
        "table_name": "{crc_id}_table".format(crc_id=crc_id),
        "value_rows": _generate_table_text(crc_params, datatype_bits),
        "output_dir": output_dir,
        "reflect": crc_params["ref_in"],
        "includes": ["#include <stdint.h>"],
        "c_includes": [],
        "preamble": "/* Auto-generated by CrcEngine {crcengine_version} */".format(
            crcengine_version=crcengine_version
        ),
        "result_mask": "0x{:x}".format((1 << crc_params["width"]) - 1),
        "requires_result_mask": crc_params["width"] != datatype_bits,
        "header_macro": "{}_H".format(crc_id.upper()),
        "msb_shift": crc_params["width"] - 8,
        "gen_files": [
            _GenFile("c_template", "{crc_id}.c".format(crc_id=crc_id)),
            _GenFile("h_template", "{crc_id}.h".format(crc_id=crc_id)),
        ],
        # The header file is required here so that it can be included in the C
        # file
        "header_file": "{crc_id}.h".format(crc_id=crc_id),
    }
    # suffix for numeric literals of the same type as the CRC
    lit_sufx = "u"
    # These are optional parameters which are checked with 'is defined' in the
    # template, if they are not defined it means that the operation the value
    # is relevant for should not be performed
    if not seed_parameter:
        template_params["seed"] = "0x{crc_param:0x}{lit_sufx}".format(
            crc_param=crc_params["seed"], lit_sufx=lit_sufx
        )
    if crc_params["xor_out"]:
        template_params["xor_out"] = "0x{crc_param:0x}{lit_sufx}".format(
            crc_param=crc_params["xor_out"], lit_sufx=lit_sufx
        )
    return template_params


def generate_test(name, output_dir):
    """Generate a Ceedling C-test wrapper for a given algorithm's generated code

    :param name: name of algorithm
    :param output_dir: directory into which output should be written
    :return:
    """
    crc_params = get_algorithm_params(name, include_check=True)
    jinja_env = _get_jinja_environment()
    template_params = _get_template_params(crc_params, output_dir, False, None, "C")
    crc_id = crc_params["name"].replace("-", "_")
    template_params["test_name"] = crc_id
    template_params["check_string"] = '"123456789"'
    template_params["crc_function"] = crc_id
    template_params["comparison"] = "TEST_ASSERT_EQUAL_HEX{}".format(
        template_params["datatype_bits"]
    )
    template_params["expected_value"] = "0x{:x}".format(crc_params["check"])
    _ensure_directory(output_dir)
    template_file = jinja_env.get_template("test_template")
    output_text = template_file.render(template_params)

    output_filename = "test_" + "{crc_id}.c".format(crc_id=crc_id)
    output_file_path = os.path.join(output_dir, output_filename)

    with open(output_file_path, "w") as f:
        f.write(output_text)


def _get_jinja_environment():
    templates_dir = _get_templates_dir()
    env = Environment(loader=FileSystemLoader(templates_dir), trim_blocks=True)
    return env


def _generate_output_files(env, template_params):
    _ensure_directory(template_params["output_dir"])
    for gen_file in template_params["gen_files"]:
        template_file = env.get_template(gen_file.template)
        output_text = template_file.render(template_params)
        output_file_path = os.path.join(template_params["output_dir"], gen_file.output)
        with open(output_file_path, "w") as f:
            f.write(output_text)


def _get_templates_dir():
    package_dir = os.path.dirname(__file__)
    templates_dir = os.path.join(package_dir, "templates")
    return templates_dir


def _get_datatype_bits(width):
    """ Return the number of  bits required for the smallest data-type that
     will accommodate a certain number of bits for a value

    :param width: Number of bits that can represent the desired datatype
    :return: Width in bits of smallest datatype
    """
    datatype_bits = 64 if width > 32 else 32 if width > 16 else 16 if width > 8 else 8
    return datatype_bits


def _generate_table_text(crc_params, datatype_bits):
    """

    :param crc_params:
    :param datatype_bits:
    :return:
    """
    # only support consistent combinations for now
    assert (
        crc_params["ref_in"] == crc_params["ref_out"]
    ), "Code generation only supported with ref_in==ref_out"
    if crc_params["ref_in"]:
        table = create_lsb_table(crc_params["poly"], crc_params["width"])
    else:
        table = create_msb_table(crc_params["poly"], crc_params["width"])
    value_rows = _make_text_from_table(table, value_width=datatype_bits // 4)
    return value_rows


def _ensure_directory(output_dir):
    new_path = pathlib.Path(output_dir)
    new_path.mkdir(parents=True, exist_ok=True)


def _make_text_from_table(
    table, max_width=79, value_width=8, indent_width=4, number_prefix="0x", number_suffix="u"
):
    """Generate the text values for a CRC lookup table

    :param table:
    :return: list of rows of table entry strings
    """
    spacer = ", "
    indent = indent_width * " "
    elements = [
        "{number_prefix}{value:0{value_width}x}{number_suffix}".format(
            number_prefix=number_prefix,
            value=value,
            value_width=value_width,
            number_suffix=number_suffix,
        )
        for value in table
    ]
    txt = spacer.join(elements)
    wrapper = textwrap.TextWrapper(
        width=max_width, initial_indent=indent, subsequent_indent=indent, break_long_words=False
    )
    wtext = wrapper.wrap(txt)
    return wtext
