"""Per-detector evidence plans and prompt focus.

The static analyzer's detectors are not interchangeable. A Fragment retention
check and a StateHolder check ask fundamentally different questions about the
code. LeakAgent's evidence selection and prompt focus should reflect that,
rather than treating every detector identically.
"""

import re
from dataclasses import dataclass, field


@dataclass
class DetectorStrategy:
    # Methods whose bodies are most likely to contain the answer.
    lifecycle_methods: list[str] = field(default_factory=list)
    # Detector-specific reasoning guidance injected into the user prompt.
    focus_prompt: str = ""
    # If True, fetch the source of the referenced type mentioned in the
    # analyzer explanation (used by StateHolderLeak).
    include_referenced_types: bool = False
    # Upper bound on the number of code blocks in the evidence bundle.
    max_code_blocks: int = 4


DETECTOR_STRATEGIES: dict[str, DetectorStrategy] = {
    "FragmentViewFieldRetentionLeak": DetectorStrategy(
        lifecycle_methods=["onDestroyView", "onCreateView", "onDestroy", "onDetach"],
        focus_prompt=(
            "This detector flags a Fragment that stores a view or ViewBinding reference in an "
            "instance field. The question is whether onDestroyView (or onDestroy) sets that field "
            "to null or calls an unbind method.\n\n"
            "Read the visible code carefully. If you can see onDestroyView setting the retained "
            "field to null, or calling unbind(), this is properly_released — the warning is a "
            "false positive.\n"
            "If onDestroyView is missing, or if it is present but does not clear the field, this "
            "is confirmed_leak.\n"
            "If you cannot see onDestroyView at all, choose inconclusive."
        ),
        include_referenced_types=False,
        max_code_blocks=4,
    ),
    "StateHolderLeak": DetectorStrategy(
        lifecycle_methods=["onDestroy", "onCleared", "onDetach"],
        focus_prompt=(
            "This detector flags a static or long-lived field that stores an object which MAY "
            "hold a UI reference. The critical question is whether the stored object ACTUALLY "
            "holds a UI reference.\n\n"
            "First, examine the declared type of the stored object. If the type is a plain data "
            "class, enum, String, primitive wrapper, POJO, or a configuration object whose type "
            "chain contains no View, Context, Activity, Fragment, or Drawable, then storing it "
            "does NOT retain UI. This is false_positive_warning — the warning is a false positive.\n\n"
            "If the stored object IS a View, Context, Activity, Fragment, Handler, Toast, "
            "Snackbar, or an object whose type chain includes any of those, then check whether "
            "the field is cleared in onDestroy or onCleared. If it is not cleared, this is "
            "confirmed_leak."
        ),
        include_referenced_types=True,
        max_code_blocks=6,
    ),
    "ThreadedUIReference": DetectorStrategy(
        lifecycle_methods=["onDestroy", "onDestroyView", "onStop", "onPause"],
        focus_prompt=(
            "This detector flags a worker thread, executor, or async task that captures a "
            "UI-scoped object. The question is whether the lifecycle method that should cancel "
            "the task actually cancels it.\n\n"
            "Look at onDestroy, onDestroyView, onStop, or onPause. If you see interrupt(), "
            "cancel(), shutdown(), shutdownNow(), or a lifecycle-aware scope (lifecycleScope, "
            "repeatOnLifecycle) that cancels the task, this is properly_released — the warning "
            "is a false positive.\n\n"
            "If the task is created but the lifecycle methods do not cancel it, this is "
            "confirmed_leak."
        ),
        include_referenced_types=False,
        max_code_blocks=4,
    ),
    "ServiceResourceManagementIssueDetector": DetectorStrategy(
        lifecycle_methods=["onStartCommand", "onDestroy", "onBind", "onUnbind"],
        focus_prompt=(
            "This detector flags a Service that may never stop.\n\n"
            "Look for stopSelf(), stopService(), or stopForeground(true) inside the visible "
            "service code. If any of these is present, the service does stop itself, so this is "
            "properly_released — the warning is a false positive.\n\n"
            "If no stop call is visible in any method, this is confirmed_leak."
        ),
        include_referenced_types=False,
        max_code_blocks=4,
    ),
    "ViewModelContextReference": DetectorStrategy(
        lifecycle_methods=["onCleared"],
        focus_prompt=(
            "This detector flags a ViewModel that stores a Context, View, FragmentManager, "
            "WebViewClient, or other UI-scoped object.\n\n"
            "First, check whether the ViewModel extends AndroidViewModel. If it does, it holds "
            "only Application context, which is process-scoped and safe. This is properly_released.\n\n"
            "If it extends a plain ViewModel and stores Activity-scoped objects (Activity, "
            "FragmentManager, View, WebViewClient), this is confirmed_leak.\n\n"
            "Careful: calling getResources() or getString() alone is not evidence of a leak. "
            "Only a direct reference to a UI-scoped object counts."
        ),
        include_referenced_types=False,
        max_code_blocks=3,
    ),
    "ImproperCallbackRegistration": DetectorStrategy(
        lifecycle_methods=["onCreate", "onCreateView", "onDestroy", "onDestroyView", "initHeader"],
        focus_prompt=(
            "This detector flags a callback registered without a LifecycleOwner, or without a "
            "matching unregister call.\n\n"
            "Look for addCallback(callback, lifecycleOwner) — the two-argument form. If the "
            "LifecycleOwner argument is present, this is properly_released.\n\n"
            "If addCallback(callback) is called with one argument, or a removeCallback is "
            "missing from onDestroy, this is confirmed_leak."
        ),
        include_referenced_types=False,
        max_code_blocks=3,
    ),
    "BillingClientLeakRisk": DetectorStrategy(
        lifecycle_methods=["onDestroy", "onStop"],
        focus_prompt=(
            "This detector flags a BillingClient that was created but never disconnected.\n\n"
            "Look for endConnection() in onDestroy. If endConnection() is present, this is "
            "properly_released — the warning is a false positive.\n\n"
            "If no endConnection() is visible in onDestroy, this is confirmed_leak."
        ),
        include_referenced_types=False,
        max_code_blocks=3,
    ),
    "FlowRetentionLeak": DetectorStrategy(
        lifecycle_methods=["onCreate", "onDestroy", "onStart", "onStop"],
        focus_prompt=(
            "This detector flags a Kotlin Flow collected in a scope that outlives the UI.\n\n"
            "Look for repeatOnLifecycle, lifecycleScope, or collectLatest in a lifecycle-aware "
            "scope. If present, this is properly_released.\n\n"
            "If the Flow is collected in a scope not tied to the UI lifecycle, this is "
            "confirmed_leak."
        ),
        include_referenced_types=False,
        max_code_blocks=3,
    ),
    "ViewBindingOpportunity": DetectorStrategy(
        lifecycle_methods=[],
        focus_prompt=(
            "This is an auxiliary modernization detector. It flags manual findViewById() usage "
            "as a migration opportunity, not as a memory leak.\n\n"
            "For LeakAgent, this detector is out of scope. Return inconclusive with low "
            "confidence. Do not attempt to judge whether the warning is a leak."
        ),
        include_referenced_types=False,
        max_code_blocks=2,
    ),
}


_REFERENCED_TYPE_RE = re.compile(r"of type '?([A-Za-z_$][\w$.]*)'?")


def get_strategy(detector: str) -> DetectorStrategy:
    return DETECTOR_STRATEGIES.get(detector, DetectorStrategy())


def extract_referenced_type(explanation: str) -> str | None:
    """Extract the referenced type from an analyzer explanation.

    Handles forms like:
      Static field 'x' of type 'android.widget.TextView' ...
      field 'mAdapter' of type com.example.Adapter ...
    """
    if not explanation:
        return None
    match = _REFERENCED_TYPE_RE.search(explanation)
    if match:
        return match.group(1)
    return None