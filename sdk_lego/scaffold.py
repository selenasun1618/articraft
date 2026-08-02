from __future__ import annotations

from sdk_lego import ArticulatedObject, Origin, TestContext, TestReport


def build_object_model() -> ArticulatedObject:
    model = ArticulatedObject(name="lego_draft_model")
    model.part("red_brick", part_num="3001", color="red", origin=Origin())
    return model


def run_tests() -> TestReport:
    ctx = TestContext(object_model)
    return ctx.report()


object_model = build_object_model()
