"""Build typed preset definitions from one allowlisted registry primitive."""

from copy import deepcopy
from dataclasses import replace

from pydantic import ValidationError, create_model

from backend.agent_tools.base import AgentToolModel, _model_properties
from backend.models.tool_configuration import CustomToolPreset, ToolMetadata
from backend.services.tool_management_service import ToolManagementError


def validate_values(definition, values):
    if set(values) - set(definition.args_model.model_fields):
        raise ToolManagementError(
            "invalid_configuration", "Unknown parameter in configuration."
        )
    for key, value in values.items():
        field = deepcopy(definition.args_model.model_fields[key])
        model = create_model(
            "ConfigurationValue",
            __base__=AgentToolModel,
            **{key: (field.annotation, field)},
        )
        try:
            model.model_validate({key: value}, strict=True)
        except ValidationError as exc:
            raise ToolManagementError(
                "invalid_configuration", f"Invalid value for {key}."
            ) from exc


def configured_model(definition, defaults, exposed=None):
    fields = {}
    for key, original in definition.args_model.model_fields.items():
        if exposed is not None and key not in exposed:
            continue
        field = deepcopy(original)
        if key in defaults:
            field.default = defaults[key]
            field.default_factory = None
        fields[key] = (field.annotation, field)
    return create_model(
        "ConfiguredToolArguments",
        __base__=definition.args_model if exposed is None else AgentToolModel,
        **fields,
    )


def metadata_definition(definition, raw):
    metadata = ToolMetadata.model_validate(raw)
    defaults = metadata.defaults or {}
    validate_values(definition, defaults)
    if (
        metadata.timeout_seconds
        and metadata.timeout_seconds > definition.spec.timeout_seconds
    ):
        raise ToolManagementError(
            "invalid_configuration", "Timeout may only be shortened."
        )
    model = configured_model(definition, defaults)
    spec = replace(
        definition.spec,
        title=metadata.title or definition.spec.title,
        description=metadata.description
        if metadata.description is not None
        else definition.spec.description,
        timeout_seconds=metadata.timeout_seconds or definition.spec.timeout_seconds,
    )
    result = replace(definition, spec=spec, args_model=model)
    validate_examples(result, metadata.examples or [])
    return result


def validate_examples(definition, examples):
    for example in examples:
        if (
            set(example) != {"id", "title", "description", "arguments"}
            or not all(
                isinstance(example[key], str) and len(example[key]) <= 1000
                for key in ("id", "title", "description")
            )
            or not isinstance(example["arguments"], dict)
        ):
            raise ToolManagementError(
                "invalid_example", "Examples require id/title/description/arguments."
            )
        try:
            definition.args_model.model_validate(example["arguments"], strict=True)
        except ValidationError as exc:
            raise ToolManagementError(
                "invalid_example", "Example arguments are invalid."
            ) from exc


def preset_definition(registry, raw):
    preset = CustomToolPreset.model_validate(raw)
    base_name = preset.template_id.removeprefix("builtin:")
    base = registry.get_definition(base_name)
    if base is None:
        raise ToolManagementError(
            "template_unavailable", "Preset template is unavailable.", 503
        )
    if set(preset.fixed_arguments) & set(preset.exposed_fields) or len(
        set(preset.exposed_fields)
    ) != len(preset.exposed_fields):
        raise ToolManagementError(
            "invalid_configuration", "Fixed and exposed fields must be distinct."
        )
    if set(preset.exposed_fields) - set(base.args_model.model_fields) or set(
        preset.defaults
    ) - set(preset.exposed_fields):
        raise ToolManagementError(
            "invalid_configuration", "Unknown or hidden exposed/default fields."
        )
    validate_values(base, {**preset.defaults, **preset.fixed_arguments})
    missing = (
        {
            key
            for key, field in base.args_model.model_fields.items()
            if field.is_required()
        }
        - set(preset.exposed_fields)
        - set(preset.fixed_arguments)
    )
    if (
        missing
        or preset.timeout_seconds
        > registry._definition_by_name[base_name].spec.timeout_seconds
    ):
        raise ToolManagementError(
            "invalid_configuration",
            "Required template fields are hidden or timeout exceeds the template.",
        )
    model = configured_model(base, preset.defaults, preset.exposed_fields)
    spec = replace(
        base.spec,
        name=preset.name,
        title=preset.title,
        description=preset.description or base.spec.description,
        input_schema=_model_properties(model),
        timeout_seconds=min(preset.timeout_seconds, base.spec.timeout_seconds),
    )

    def execute(context, args):
        # Base execute rechecks primitive policy and the executor enforces trusted scope.
        result = registry.execute(
            base_name,
            **{
                **preset.fixed_arguments,
                **args.model_dump(mode="json"),
                **context.model_dump(mode="json"),
            },
        )
        return replace(result, tool_name=preset.name)

    definition = replace(base, spec=spec, args_model=model, executor=execute)
    validate_examples(definition, preset.examples)
    return definition
