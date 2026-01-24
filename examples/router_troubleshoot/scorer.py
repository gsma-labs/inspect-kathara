"""Custom scorer for router troubleshooting task."""

from inspect_ai.scorer import Score, CORRECT, INCORRECT, scorer, accuracy, stderr
from inspect_ai.util import sandbox

PC2_IP = "10.0.2.10"


@scorer(metrics=[accuracy(), stderr()])
def router_fix_scorer():
    """Tests connectivity by pinging from PC1 to PC2."""

    async def score(_state, _target) -> Score:
        try:
            pc1_sandbox = sandbox("pc1")
        except (ProcessLookupError, ValueError) as e:
            return Score(value=INCORRECT, answer="No sandbox", explanation=f"Could not get PC1 sandbox: {e}")

        result = await pc1_sandbox.exec(["ping", "-c", "1", "-W", "5", PC2_IP])

        if result.success and result.returncode == 0:
            return Score(
                value=CORRECT,
                answer="Connection successful",
                explanation=f"PC1 can ping PC2 ({PC2_IP}). Router forwarding works.",
            )

        ping_output = result.stdout[:200] if result.stdout else result.stderr[:200]
        return Score(
            value=INCORRECT,
            answer="Connection failed",
            explanation=f"PC1 cannot ping PC2 ({PC2_IP}). Output: {ping_output}",
        )

    return score
