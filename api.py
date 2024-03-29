from quart import Quart, jsonify, request, Blueprint
from quart.views import View
from marshmallow import Schema, fields, EXCLUDE
import json
import re
import uvicorn
import requests
from dark_theme_css import CSS
from config import APIS, PORT
from ParseABI import parse_abi


CONFIG_DICT = {}


class ABITypeSchema(Schema):
    class Meta:
        ordered = True
        unknown = EXCLUDE

    name = fields.Str(required=True)
    mutability = fields.Str(required=True)
    inputs = fields.List(fields.Dict(), required=True)
    outputs = fields.List(fields.Dict())


def resolve_input_type(input_type):
    cleaned_type = re.sub(r"<.*?>", "", input_type)
    cleaned_type = re.sub(r"optional|variadic", "", cleaned_type)
    datatypes = {
        "BigUint": "integer",
        "u64": "integer",
        "Address": "string",
        "bool": "boolean",
        "TokenIdentifier": "string",
        "EgldOrEsdtTokenIdentifier": "string",
        "u32": "integer",
        "u8": "integer"
    }
    return datatypes.get(cleaned_type, "string")


def resolve_output_type(name, output_type):
    basic_types = {
        'i8': {'type': 'integer', 'example': 1},
        'i16': {'type': 'integer', 'example': 12},
        'i32': {'type': 'integer', 'example': 1234},
        'i64': {'type': 'integer', 'example': 12345678},
        'u8': {'type': 'integer', 'example': 1},
        'u16': {'type': 'integer', 'example': 12},
        'u32': {'type': 'integer', 'example': 1234},
        'u64': {'type': 'integer', 'example': 12345678},
        'isize': {'type': 'integer', 'example': 1},
        'usize': {'type': 'integer', 'example': 1},
        'bytes': {'type': 'string', 'example': 'When the time of the White Frost comes, do not eat the yellow snow!'},
        'bool': {'type': 'boolean', 'example': False},
        'BigUint': {'type': 'string', 'example': '69000000000000000000'},
        'BigInt': {'type': 'string', 'example': '69000000000000000000'},
        'EgldOrEsdtTokenIdentifier': {'type': 'string', 'example': 'EGLD'},
        'TokenIdentifier': {'type': 'string', 'example': 'ELLAMA-6c0295'},
        'Address': {'type': 'string', 'example': 'erd1ccxmfaganejartfyr9ack4lnudxam8ezzwn23k3x5nls97rjaeds7f2wu2'}
    }

    conditions = {
        'variadic': lambda subtype: {
            'type': 'array',
            'items': resolve_output_type(name, subtype),
            'example': [resolve_output_type(name, subtype)['example']]
        },
        'List': lambda subtype: {
            'type': 'array',
            'items': resolve_output_type(name, subtype),
            'example': [resolve_output_type(name, subtype)['example']]
        },
        'vec': lambda subtype: {
            'type': 'array',
            'items': resolve_output_type(name, subtype),
            'example': [resolve_output_type(name, subtype)['example']]
        },
        'Option': lambda subtype: {
            'type': resolve_output_type(name, subtype)['type'],
            'nullable': True,
            'example': resolve_output_type(name, subtype)['example']
        },
        'optional': lambda subtype: resolve_output_type(name, subtype),
        'tuple': lambda subtype: {
            'type': 'array',
            'items': [resolve_output_type(name, subtype_item) for subtype_item in subtype],
            'example': [resolve_output_type(name, subtype_item)['example'] for subtype_item in subtype]
        },
        'enum': lambda subtype: {
            'type': 'string',
            'example': 'enum_value'
        },
        'multi': lambda subtype: {
            'type': 'array',
            'items': resolve_output_type(name, subtype),
            'example': [resolve_output_type(name, subtype)['example']]
        }
    }

    if isinstance(output_type, list):
        output_type = output_type[0]

    if isinstance(output_type, str):
        if output_type in basic_types:
            resolved_type = basic_types[output_type]
        elif output_type.startswith(('optional<', 'Option<')):
            subtype = output_type[output_type.index('<') + 1:-1]
            resolved_type = conditions['Option'](subtype)
        elif output_type.startswith(('variadic<', 'List<', 'vec<', 'multi<')):
            subtype = output_type[output_type.index('<') + 1:-1]
            resolved_type = conditions[output_type[:output_type.index('<')]](subtype)
        elif output_type in conditions:
            resolved_type = conditions[output_type](output_type)
        else:
            custom_type = CONFIG_DICT[name]["types"].get(output_type)
            if custom_type:
                if custom_type['type'] == 'enum':
                    enum_variants = custom_type['variants']
                    enum_values = [variant['name'] for variant in enum_variants]
                    resolved_type = {'type': 'string', 'enum': enum_values, 'example': enum_values[0]}
                else:
                    fields = custom_type['fields']
                    resolved_fields = {
                        field['name']: resolve_output_type(name, field['type'])
                        for field in fields
                    }
                    resolved_type = {
                        'type': 'object',
                        'properties': resolved_fields,
                        'example': {field['name']: resolve_output_type(name, field['type'])['example'] for field in fields}
                    }
            else:
                if ',' in output_type and '<' not in output_type and '>' not in output_type:
                    subtypes = [subtype.strip() for subtype in output_type.split(',')]
                    resolved_type = {
                        'type': 'array',
                        'items': [resolve_output_type(name, subtype) for subtype in subtypes],
                        'example': [resolve_output_type(name, subtype)['example'] for subtype in subtypes]
                    }
                else:
                    resolved_type = {'type': 'Unknown Type: ' + output_type, 'example': 'unknown'}
                    if resolved_type['type'].startswith('Unknown Type: Unknown Type: '):
                        resolved_type['type'] = resolved_type['type'][18:]  # Remove the duplicated prefix
        return resolved_type
    else:
        # If the output type is not a string, it means it's already resolved, so return as is
        return output_type


def create_endpoint_resource_class(endpoint_data):
    swagger_parameters = []  # List to hold the Swagger parameters

    for input_data in endpoint_data['inputs']:
        input_name = input_data['name']
        input_type = input_data['type']
        multi_arg = input_data.get('multi_arg', False)

        # Generate Swagger parameter definition for each input
        swagger_parameter = {
            'name': input_name,
            'in': 'query',
            'required': True if not input_type.startswith("optional") else False
        }

        # Determine the data type of the input parameter
        if multi_arg:
            swagger_parameter['type'] = 'array'
            swagger_parameter['items'] = {
                'type': 'string'
            }
        else:
            swagger_parameter['type'] = resolve_input_type(input_type)
        swagger_parameters.append(swagger_parameter)
    class_name = f"EndpointResource_{endpoint_data['name']}"

    class EndpointResource(View):
        async def dispatch_request(self):
            url_rule = request.url_rule
            if url_rule:
                app_name = url_rule.rule.split('/')[1]  # Assuming the app name is the first part of the URL path
            else:
                app_name = "Unknown"
            inputs = {}
            args = []
            scaddress = str(request.args.get("smartcontractaddress", default=CONFIG_DICT[app_name]["SCADDRESS"]))
            for input_data in endpoint_data['inputs']:
                input_name = input_data['name']
                input_value = str(request.args.get(input_name, default=''))
                is_optional = input_data['type'].startswith("optional")
                is_multi_arg = input_data.get('multi_arg', False)

                if is_multi_arg:
                    input_values = input_value.split(',')
                    inputs[input_name] = input_values
                else:
                    inputs[input_name] = input_value

                if is_optional:
                    args.append({
                        "value": inputs[input_name][0] if is_multi_arg else inputs[input_name],
                        "type": input_data["type"]
                    })
                else:
                    args.append({
                        "value": str(input_value),
                        "type": input_data["type"]
                    })

            # Process the input and call the smart contract based on the endpoint name
            output = await parse_abi(scaddress, endpoint_data["name"], CONFIG_DICT[app_name]["endpoints"], CONFIG_DICT[app_name]["abi_json"], args)
            code, output = output
            if code != 200:
                message = {"error": output}
                response = jsonify(message)
                response.status_code = code
                return response

            return jsonify(output)

    EndpointResource.__name__ = class_name
    return EndpointResource


def generate_custom_swagger_json(name=""):
    display_name = name.replace('/', '')
    # Generate the Swagger JSON specification
    swagger_json = {
        'swagger': '2.0',
        'info': {
            'title': f"ABI2API - API for Smart Contract: {CONFIG_DICT[display_name]['abi_json']['name']}",
            'description': f'## Description\nSwagger API documentation for ABI JSON on the MultiversX Blockchain.\n## Credits\nBuilt by: SkullElf\nFeel free to follow Bobbet on <a href=\"https://twitter.com/BobbetBot\">Twitter</a>\nHuge thanks to everyone who supported and tested this tool, and mainly:\n* XOXNO\'s team\n* uPong (Enzo Foucaud)\n* Martin Wagner - Knights of Cathena \n\n## Details\nThis API instance provides data from a smart contract in the address: <a href=\"https://explorer.multiversx.com/accounts/{CONFIG_DICT[display_name]["SCADDRESS"]}\">{CONFIG_DICT[display_name]["SCADDRESS"]}</a>',
            'version': '1.0'
        },
        'paths': {},
        'definitions': {},
        'tags': [
            {
                'name': name.replace('/', ''),
                'description': f'Endpoints with `readonly` mutability for smart contract: `{name.replace("/", "")}`'
            }
        ]
    }

    for endpoint in CONFIG_DICT[display_name]["endpoints"]:
        if endpoint["mutability"] == "readonly":
            schema = ABITypeSchema()
            endpoint_data = schema.load(endpoint)
            # Generate the path for the Swagger JSON specification
            swagger_path = f"/{name}{endpoint['name']}"
            swagger_parameters = []
            for input_data in endpoint_data['inputs']:
                input_name = input_data['name']
                input_type = input_data['type']
                is_optional = input_type.startswith("optional")
                is_multi_arg = input_data.get('multi_arg', False)
                # Determine the data type of the input parameter
                if input_type.startswith("optional<"):
                    input_type = input_type[9:-1]
                swagger_parameter = {
                    'name': input_name,
                    'in': 'query',
                    'required': not is_optional
                }
                if is_multi_arg:
                    swagger_parameter['type'] = 'array'
                    swagger_parameter['items'] = {
                        'type': 'string'
                    }
                elif input_type == "u32":
                    swagger_parameter['type'] = 'integer'
                else:
                    swagger_parameter['type'] = 'string'
                swagger_parameters.append(swagger_parameter)
            # Additional handling for the "docs" field
            if "docs" in endpoint:
                description = "\n".join(endpoint["docs"])
            else:
                description = f"No documentation available for {endpoint['name']}."
            swagger_json['paths'][swagger_path] = {
                'get': {
                    'summary': endpoint['name'],
                    'description': description,
                    'parameters': swagger_parameters,
                    'responses': {
                        '200': {
                            'description': 'Success',
                            'schema': {
                                'type': 'object',
                                'properties': {
                                    output_data.get('name', 'output'): resolve_output_type(
                                        display_name,
                                        output_data.get('type', 'output'))
                                    for output_data in endpoint.get('outputs', [])
                                }
                            }
                        }
                    },
                    'tags': [display_name]
                }
            }
            # Generate the definition for the Swagger JSON specification
            swagger_definition = {
                'type': 'object',
                'properties': {
                    output_data.get('name', 'output'): resolve_output_type(display_name, output_data.get('type', 'output'))
                    for output_data in endpoint.get('outputs', [])
                }
            }
            swagger_json['definitions'][f"{endpoint['name']}_response"] = swagger_definition
            # Update the Swagger parameter to represent the multi_arg input as an array
            for parameter in swagger_parameters:
                if parameter['name'] in endpoint_data['inputs']:
                    parameter['x-multi-item'] = True

    return swagger_json


def create_api_blueprint(sc_address, abi_path, name=""):
    bp = Blueprint(name, __name__)
    # Load ABI JSON from the internet
    if abi_path.startswith("https://") or abi_path.startswith("http://"):
        abi_json = requests.get(abi_path).json()
    else:
        # Load ABI JSON from file
        with open(abi_path) as f:
            abi_json = json.load(f)
    endpoints = abi_json["endpoints"]
    types = abi_json["types"]
    CONFIG_DICT[name.replace('/', '')] = {
        "abi_json": abi_json,
        "types": types,
        "endpoints": endpoints,
        "SCADDRESS": sc_address
    }

    @bp.route(f'/api/{name}swagger.json')
    async def custom_swagger():
        return jsonify(generate_custom_swagger_json(name))

    @bp.route(f'/{name}')
    async def api_docs():
        swagger_ui_html = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>ABI2API - {name.replace('/', '')}</title>
            <link rel="icon" type="image/png" size="32x32" href="https://wallet.multiversx.com/favicon-32x32.png">
            <link rel="stylesheet" type="text/css" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/3.52.1/swagger-ui.min.css">
            <script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/3.52.1/swagger-ui-bundle.min.js"></script>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/3.52.1/swagger-ui-standalone-preset.min.js"></script>

            <style>
        ''' + CSS + '''

      </style>
        </head>
        <body>
    <div class="topbar"><div class="wrapper"><div class="topbar-wrapper"><center><img src="https://cdn.discordapp.com/attachments/1002615966598967358/1131252032616005812/new_logo.png" height=50% width=50%/></center></div></div></div>
            <div id="swagger-ui"></div>
            <script>
                SwaggerUIBundle({
                    url: window.location.origin + "/" + ''' + f"'api/{name}swagger.json'," + '''
                    dom_id: '#swagger-ui',
                    deepLinking: true,
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIStandalonePreset
                    ]
                });
            </script>
        </body>

        </html>
        '''
        return swagger_ui_html

    # Register the resource classes
    for endpoint in CONFIG_DICT[name.replace('/', '')]["endpoints"]:
        if endpoint["mutability"] == "readonly":
            schema = ABITypeSchema()
            endpoint_data = schema.load(endpoint)
            resource_class = create_endpoint_resource_class(endpoint_data)
            endpoint_name = endpoint['name']

            # Add the route
            bp.add_url_rule(
                f"/{name}{endpoint_name}",
                view_func=resource_class.as_view(endpoint_name),
                methods=['GET']
            )
    return bp


if __name__ == '__main__':
    app = Quart(__name__)
    for process in APIS:
        app_name = f"{process['NAME']}/"
        app.register_blueprint(create_api_blueprint(process["SCADDRESS"], process["ABI_PATH"], app_name))


    uvicorn.run(app, port=PORT)

