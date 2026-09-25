from __future__ import annotations

from .executors import (
    AgentLoopExecutor,
    ApiCallerExecutor,
    ApprovalExecutor,
    ChatLikeExecutor,
    CodegenExecutor,
    HttpRequestExecutor,
    IfElseExecutor,
    InputExecutor,
    LangfuseTracerExecutor,
    LangsmithTracerExecutor,
    LiteLlmExecutor,
    LoudFailureExecutor,
    OutputExecutor,
    PromptTemplateExecutor,
    SchemaValidateExecutor,
    SubWorkflowExecutor,
    SwitchExecutor,
    TraceLogExecutor,
    VectorStoreExecutor,
    WaitExecutor,
    WebhookTriggerExecutor,
    WebSearchExecutor,
    XWS3Executor,
    XWSApigwRegisterExecutor,
    XWSAuditExecutor,
    XWSDmsIntrospectExecutor,
    XWSEventTriggerExecutor,
    XWSGatewayLLMExecutor,
    XWSIAMEvaluateExecutor,
    XWSLambdaInvokeExecutor,
    XWSRelayNotifyExecutor,
)
from .registry import NodeRegistry


def create_default_registry() -> NodeRegistry:
    default_executor = LoudFailureExecutor()
    registry = NodeRegistry(default_executor=default_executor)
    registry.register(InputExecutor())
    registry.register(PromptTemplateExecutor())
    registry.register(ChatLikeExecutor())
    registry.register(LiteLlmExecutor())
    registry.register(HttpRequestExecutor())
    registry.register(ApiCallerExecutor())
    registry.register(WebhookTriggerExecutor())
    registry.register(XWSEventTriggerExecutor())
    registry.register(TraceLogExecutor())
    registry.register(LangfuseTracerExecutor())
    registry.register(LangsmithTracerExecutor())
    registry.register(SwitchExecutor())
    registry.register(IfElseExecutor())
    registry.register(WaitExecutor())
    registry.register(ApprovalExecutor())
    registry.register(OutputExecutor())
    registry.register(XWS3Executor())
    registry.register(XWSLambdaInvokeExecutor())
    registry.register(XWSIAMEvaluateExecutor())
    registry.register(XWSRelayNotifyExecutor())
    registry.register(XWSGatewayLLMExecutor())
    registry.register(XWSDmsIntrospectExecutor())
    registry.register(XWSApigwRegisterExecutor())
    registry.register(XWSAuditExecutor())
    registry.register(AgentLoopExecutor())
    registry.register(SchemaValidateExecutor())
    registry.register(CodegenExecutor())
    registry.register(SubWorkflowExecutor())
    registry.register(VectorStoreExecutor())
    registry.register(WebSearchExecutor())
    return registry
