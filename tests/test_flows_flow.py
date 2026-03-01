"""Tests for hof.flows.flow."""

from __future__ import annotations

import pytest

from hof.core.registry import registry
from hof.flows.flow import Flow


class TestFlowConstruction:
    def test_flow_registers_itself(self):
        flow = Flow("my_flow")
        assert registry.get_flow("my_flow") is flow

    def test_flow_starts_with_no_nodes(self):
        flow = Flow("empty_flow")
        assert flow.nodes == {}

    def test_flow_name(self):
        flow = Flow("named_flow")
        assert flow.name == "named_flow"


class TestFlowNodeDecorator:
    def test_bare_node_decorator(self):
        flow = Flow("flow1")

        @flow.node
        def step_a(x: int) -> dict:
            return {"x": x}

        assert "step_a" in flow.nodes
        assert flow.nodes["step_a"].name == "step_a"

    def test_node_decorator_with_args(self):
        flow = Flow("flow2")

        @flow.node(retries=2, timeout=90)
        def step_a() -> dict:
            return {}

        assert flow.nodes["step_a"].retries == 2
        assert flow.nodes["step_a"].timeout == 90

    def test_node_with_depends_on(self):
        flow = Flow("flow3")

        @flow.node
        def step_a() -> dict:
            return {}

        @flow.node(depends_on=[step_a])
        def step_b() -> dict:
            return {}

        assert flow.nodes["step_b"].depends_on == ["step_a"]

    def test_node_function_still_callable(self):
        flow = Flow("flow4")

        @flow.node
        def add(a: int, b: int) -> dict:
            return {"sum": a + b}

        assert add(a=1, b=2) == {"sum": 3}

    def test_add_node_method(self):
        flow = Flow("flow5")

        def standalone(x: int) -> dict:
            return {"x": x}

        flow.add_node(standalone)
        assert "standalone" in flow.nodes

    def test_add_node_with_depends_on(self):
        flow = Flow("flow6")

        @flow.node
        def step_a() -> dict:
            return {}

        def step_b() -> dict:
            return {}

        flow.add_node(step_b, depends_on=[step_a])
        assert flow.nodes["step_b"].depends_on == ["step_a"]


class TestFlowValidation:
    def test_valid_flow(self, simple_flow):
        errors = simple_flow.validate()
        assert errors == []

    def test_empty_flow_invalid(self):
        flow = Flow("empty_flow")
        errors = flow.validate()
        assert any("no nodes" in e.lower() for e in errors)

    def test_missing_dependency_detected(self):
        flow = Flow("bad_flow")

        @flow.node(depends_on=["nonexistent_node"])
        def step_a() -> dict:
            return {}

        errors = flow.validate()
        assert any("nonexistent_node" in e for e in errors)

    def test_cycle_detected(self):
        flow = Flow("cyclic_flow")

        @flow.node(depends_on=["step_b"])
        def step_a() -> dict:
            return {}

        @flow.node(depends_on=["step_a"])
        def step_b() -> dict:
            return {}

        errors = flow.validate()
        assert any("cycle" in e.lower() for e in errors)


class TestFlowExecutionOrder:
    def test_linear_order(self, simple_flow):
        waves = simple_flow.get_execution_order()
        assert len(waves) == 3
        assert waves[0] == ["step_a"]
        assert waves[1] == ["step_b"]
        assert waves[2] == ["step_c"]

    def test_branching_order(self, branching_flow):
        waves = branching_flow.get_execution_order()
        assert waves[0] == ["start"]
        # branch_a and branch_b can run in parallel
        assert set(waves[1]) == {"branch_a", "branch_b"}
        assert waves[2] == ["merge"]

    def test_single_node_order(self):
        flow = Flow("single_node_flow")

        @flow.node
        def only_step() -> dict:
            return {}

        waves = flow.get_execution_order()
        assert waves == [["only_step"]]

    def test_cycle_raises_in_execution_order(self):
        flow = Flow("cyclic_exec_flow")
        # Manually inject a cycle bypassing validation
        from hof.flows.node import NodeMetadata

        def fn_a() -> dict:
            return {}

        def fn_b() -> dict:
            return {}

        flow.nodes["a"] = NodeMetadata(name="a", fn=fn_a, depends_on=["b"])
        flow.nodes["b"] = NodeMetadata(name="b", fn=fn_b, depends_on=["a"])

        with pytest.raises(ValueError, match="Cycle detected"):
            flow.get_execution_order()

    def test_entry_nodes(self, simple_flow):
        entries = simple_flow.get_entry_nodes()
        assert len(entries) == 1
        assert entries[0].name == "step_a"

    def test_branching_entry_nodes(self, branching_flow):
        entries = branching_flow.get_entry_nodes()
        assert len(entries) == 1
        assert entries[0].name == "start"


class TestFlowToDict:
    def test_to_dict_structure(self, simple_flow):
        d = simple_flow.to_dict()
        assert d["name"] == "test_simple_flow"
        assert "nodes" in d
        assert "execution_order" in d
        assert set(d["nodes"].keys()) == {"step_a", "step_b", "step_c"}

    def test_to_dict_node_serialization(self, simple_flow):
        d = simple_flow.to_dict()
        step_b = d["nodes"]["step_b"]
        assert step_b["depends_on"] == ["step_a"]
