from pathlib import Path

DETECTOR_FILES = {
    "BillingClientLeakRisk.json": "BillingClientLeakRisk",
    "FlowRetentionLeak.json": "FlowRetentionLeak",
    "FragmentViewFieldRetentionLeak.json": "FragmentViewFieldRetentionLeak",
    "ImproperCallbackRegistration.json": "ImproperCallbackRegistration",
    "ServiceResourceManagementIssueDetector.json": "ServiceResourceManagementIssueDetector",
    "StateHolderLeak.json": "StateHolderLeak",
    "ThreadedUIReference.json": "ThreadedUIReference",
    "ViewBindingOpportunity.json": "ViewBindingOpportunity",
    "ViewModelContextReference.json": "ViewModelContextReference",
}

DETECTOR_ALIASES = {
    "BillingClientLeakRisk": "BillingClientLeakRisk",
    "BillingClientCleanup": "BillingClientLeakRisk",
    "FlowRetentionLeak": "FlowRetentionLeak",
    "FlowRetention": "FlowRetentionLeak",
    "FragmentViewFieldLeak": "FragmentViewFieldRetentionLeak",
    "FragmentViewFieldRetentionLeak": "FragmentViewFieldRetentionLeak",
    "ImproperCallbackReg": "ImproperCallbackRegistration",
    "ImproperCallbackRegistration": "ImproperCallbackRegistration",
    "ServiceResourceMgmt": "ServiceResourceManagementIssueDetector",
    "ServiceResourceManagement": "ServiceResourceManagementIssueDetector",
    "ServiceResourceManagementIssueDetector": "ServiceResourceManagementIssueDetector",
    "StateHolderLeak": "StateHolderLeak",
    "ThreadedUIReference": "ThreadedUIReference",
    "ViewBindingOpportunity": "ViewBindingOpportunity",
    "ViewModelContextRef": "ViewModelContextReference",
    "ViewModelContextReference": "ViewModelContextReference",
}

CORE_DETECTORS = {
    "BillingClientLeakRisk", "FlowRetentionLeak", "FragmentViewFieldRetentionLeak",
    "ImproperCallbackRegistration", "StateHolderLeak", "ThreadedUIReference",
    "ViewModelContextReference",
}
ADJACENT_DETECTORS = {"ServiceResourceManagementIssueDetector"}
AUXILIARY_DETECTORS = {"ViewBindingOpportunity"}

PAPER_TABLE_VII = {
    "BillingClientLeakRisk": {"TP": 1, "FP": 0, "UNSURE": 0},
    "FlowRetentionLeak": {"TP": 0, "FP": 4, "UNSURE": 0},
    "FragmentViewFieldRetentionLeak": {"TP": 80, "FP": 0, "UNSURE": 0},
    "ImproperCallbackRegistration": {"TP": 14, "FP": 0, "UNSURE": 0},
    "ServiceResourceManagementIssueDetector": {"TP": 37, "FP": 3, "UNSURE": 0},
    "StateHolderLeak": {"TP": 40, "FP": 18, "UNSURE": 2},
    "ThreadedUIReference": {"TP": 75, "FP": 4, "UNSURE": 1},
    "ViewBindingOpportunity": {"TP": 96, "FP": 4, "UNSURE": 0},
    "ViewModelContextReference": {"TP": 9, "FP": 0, "UNSURE": 0},
}

IGNORED_SOURCE_DIRS = {".git", ".gradle", ".idea", "build", "out", "node_modules", "target"}

def canonical_detector(value: str) -> str:
    value = (value or "").strip()
    return DETECTOR_ALIASES.get(value, value)

def detector_group(detector: str) -> str:
    if detector in CORE_DETECTORS: return "core"
    if detector in ADJACENT_DETECTORS: return "adjacent"
    if detector in AUXILIARY_DETECTORS: return "auxiliary"
    return "unknown"

