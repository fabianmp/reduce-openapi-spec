import copy
import json
import re
from dataclasses import dataclass
from itertools import groupby

import streamlit as st


@dataclass
class Operation:
    op_id: str
    verb: str
    path: str
    summary: str
    tag: str
    schemas: list[str]

    def get_key(self):
        return f"{self.verb}-{self.path}"


st.set_page_config("Reduce OpenAPI Spec", layout="wide")
st.sidebar.title("Reduce OpenAPI Spec")


def add_missing_schemas(schema, all_schemas, schema_list):
    matches = re.findall(r"#/components/schemas/(\w+)", all_schemas[schema])
    new_matches = [m for m in matches if m not in schema_list]
    schema_list.extend(new_matches)
    for m in new_matches:
        add_missing_schemas(m, all_schemas, schema_list)


def add_schemas_from_operation(data, schemas):
    content = data.get("content")
    if content is None:
        return
    for response_type in content.values():
        schema = response_type.get("schema", {}).get("$ref")
        if schema is not None:
            schemas.append(schema.replace("#/components/schemas/", ""))


def parse_path(path, operations, all_schemas):
    result = []
    for verb, op in operations.items():
        schemas = []
        body = op.get("requestBody")
        if body is not None:
            add_schemas_from_operation(body, schemas)
        for response in op["responses"].values():
            add_schemas_from_operation(response, schemas)
        for schema in set(schemas):
            add_missing_schemas(schema, all_schemas, schemas)
        tags_list = op.get("tags", [])
        tag = tags_list[0] if tags_list else "No tag"
        result.append(
            Operation(
                op_id=op.get("operationId"),
                verb=verb,
                path=path,
                summary=op.get("summary"),
                tag=tag,
                schemas=list(set(schemas)),
            )
        )

    return result


@st.cache_data
def load_api_spec(openapi_file):
    try:
        spec = json.load(openapi_file)
        if spec.get("openapi") is None:
            raise Exception("Not a valid openapi 3.0.1 file")
    except Exception as e:
        st.error(e)
        st.stop()
    schemas = {k: json.dumps(v) for k, v in spec["components"]["schemas"].items()}

    operations_list: list[Operation] = []
    for path, path_operations in spec["paths"].items():
        operations_list.extend(parse_path(path, path_operations, schemas))

    operations = {op.op_id: op for op in operations_list}

    group_operations = {}
    for tag, group in groupby(operations.values(), lambda x: x.tag):
        group_operations.setdefault(tag, [])
        group_operations[tag].extend(group)
    return spec, schemas, operations, group_operations


openapi_file = st.sidebar.file_uploader("OpenAPI Spec", "json")
if openapi_file is None:
    st.stop()

spec, schemas, operations, group_operations = load_api_spec(openapi_file)

for tag, group in sorted(group_operations.items(), key=lambda x: x[0]):
    st.subheader(tag)
    for op in sorted(group, key=lambda x: x.path):
        cols = st.columns([0.05, 0.05, 0.3, 0.1, 0.5], vertical_alignment="center")
        cols[0].toggle("select", key=op.op_id, label_visibility="collapsed")
        cols[1].write(op.verb.upper())
        cols[2].write(op.path)
        cols[3].write(f"{len(op.schemas)} schemas")
        cols[4].write(op.summary)

for key in list(st.session_state.keys()):
    if key not in operations:
        del st.session_state[key]

selected_operations = [str(k) for k, v in st.session_state.items() if v]
selected_schemas = []

for operation_id in selected_operations:
    selected_schemas.extend(operations[operation_id].schemas)

selected_schemas = list(set(selected_schemas))

st.sidebar.subheader("Selected:")
st.sidebar.progress(
    len(selected_operations) / len(operations),
    f"Operations ({len(selected_operations)}/{len(operations)})",
)
st.sidebar.progress(
    len(selected_schemas) / len(schemas),
    f"Schemas ({len(selected_schemas)}/{len(schemas)})",
)

reduced_spec = copy.deepcopy(spec)
reduced_spec["paths"] = {}
reduced_spec["components"]["schemas"] = {}

for operation_id in selected_operations:
    operation = operations[operation_id]
    reduced_spec["paths"].setdefault(operation.path, {})
    reduced_spec["paths"][operation.path][operation.verb] = spec["paths"][
        operation.path
    ][operation.verb]

for schema in selected_schemas:
    reduced_spec["components"]["schemas"][schema] = spec["components"]["schemas"][
        schema
    ]

st.sidebar.download_button(
    "Download reduced OpenAPI spec",
    json.dumps(reduced_spec, indent=2),
    f"reduced_{openapi_file.name}",
    mime="application/json",
)
