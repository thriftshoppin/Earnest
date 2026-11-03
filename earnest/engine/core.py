"""Composable engine core: components exchange versioned artifacts, not CLI state."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class Artifact:
    """A typed engine value with provenance and optional inference confidence."""
    schema: str
    value: Any
    source: str | None = None
    confidence: float | None = None
    notes: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComponentContext:
    inputs: Mapping[str, Artifact]
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ControlParameter:
    """A user-facing dial declared by a component and mapped to engine semantics."""
    id: str
    label: str
    unit: str
    minimum: float | None
    maximum: float | None
    default: float | str
    maps_to: str
    role: str
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComponentRun:
    name: str
    status: str
    elapsed_ms: float
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]


class EngineComponent(Protocol):
    """An engine extension declares its ports and transforms artifacts."""
    name: str
    requires: tuple[str, ...]
    provides: tuple[str, ...]

    def process(self, context: ComponentContext) -> Mapping[str, Artifact | Any]: ...


class RealtimeAudioComponent(Protocol):
    """Block-processing contract for live audio endpoints and DSP components.

    Implementations must declare their sample/channel format, prepare buffers before
    streaming, accept control updates outside the audio callback, and process blocks
    without file I/O. Hard real-time implementations belong in native code.
    """
    name: str

    def prepare(self, sample_rate: int, max_block_size: int, input_channels: int,
                output_channels: int) -> None: ...

    def set_controls(self, controls: Mapping[str, float]) -> None: ...

    def process_block(self, input_block: Any, output_block: Any, frames: int) -> None: ...

    def close(self) -> None: ...


class EngineError(ValueError):
    """Invalid component graph, missing input, or malformed component result."""


@dataclass(frozen=True)
class EngineResult:
    artifacts: Mapping[str, Artifact]
    runs: tuple[ComponentRun, ...]


class Engine:
    """Run an explicit workflow from registered components.

    The engine owns artifact validation, provenance, and run reporting. Components
    own domain logic; the CLI and future application adapters only assemble workflows.
    """

    def __init__(self) -> None:
        self._components: dict[str, EngineComponent] = {}
        self._realtime_components: dict[str, RealtimeAudioComponent] = {}

    @property
    def components(self) -> tuple[str, ...]:
        return tuple(self._components)

    @property
    def realtime_components(self) -> tuple[str, ...]:
        return tuple(self._realtime_components)

    def parameters(self, component_name: str) -> tuple[ControlParameter, ...]:
        component = self._components.get(component_name)
        if component is None:
            raise EngineError("unknown batch component %r" % component_name)
        return tuple(getattr(component, "parameters", ()))

    def register(self, component: EngineComponent) -> None:
        if not component.name or component.name in self._components:
            raise EngineError("component name is empty or already registered: %r" % component.name)
        if len(set(component.provides)) != len(component.provides):
            raise EngineError("component %s declares duplicate output ports" % component.name)
        self._components[component.name] = component

    def register_realtime(self, component: RealtimeAudioComponent) -> None:
        if not component.name or component.name in self._realtime_components:
            raise EngineError("real-time component name is empty or already registered: %r" % component.name)
        self._realtime_components[component.name] = component

    def execute(self, workflow: Sequence[str], inputs: Mapping[str, Artifact],
                options: Mapping[str, Mapping[str, Any]] | None = None) -> EngineResult:
        artifacts = dict(inputs)
        options = options or {}
        runs = []
        for name in workflow:
            if name not in self._components:
                raise EngineError("unknown component %r; registered: %s" % (name, ", ".join(self.components)))
            component = self._components[name]
            missing = [port for port in component.requires if port not in artifacts]
            if missing:
                raise EngineError("component %s needs missing artifact(s): %s" % (name, ", ".join(missing)))
            started = perf_counter()
            produced = component.process(ComponentContext(
                {port: artifacts[port] for port in component.requires}, options.get(name, {})))
            if not isinstance(produced, Mapping):
                raise EngineError("component %s did not return an artifact mapping" % name)
            expected, actual = set(component.provides), set(produced)
            if actual != expected:
                raise EngineError("component %s outputs %s; declared %s" %
                                  (name, sorted(actual), sorted(expected)))
            for port, item in produced.items():
                artifact = item if isinstance(item, Artifact) else Artifact("earnest.value.v1", item)
                artifacts[port] = Artifact(artifact.schema, artifact.value, artifact.source,
                                           artifact.confidence, artifact.notes,
                                           artifact.provenance + (name,))
            runs.append(ComponentRun(name, "ok", (perf_counter() - started) * 1000.0,
                                     component.requires, component.provides))
        return EngineResult(artifacts, tuple(runs))
