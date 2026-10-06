"""Cloud SRE Agent — Release/Configure/Monitor stages. Canary deploy, verify, promote or roll back."""
import asyncio

from .base import Agent

SYSTEM = """You are the Cloud SRE Agent of AutoSRE-0. Write a concise incident report in Markdown from the data.
Return JSON: {"title": str, "body": str}."""


class SREAgent(Agent):
    name = "sre-agent"

    async def deploy(self, image: str) -> dict:
        """Deploy with zero traffic under a canary tag, verify it, then promote."""
        dep = await self.hub.call("deploy_cloud_run", image=image, tag="canary")
        canary_url = dep["url"].replace("https://", "https://canary---")
        hc = await self.hub.call("health_check", url=canary_url)
        self.say(f"Canary health: {hc}")
        if not hc["ok"]:
            await self._incident(f"Canary {dep['revision']} failed health check", hc)
            return {"promoted": False, "revision": dep["revision"], "health": hc}
        await self.hub.call("promote", revision=dep["revision"])
        self.state.set("last_revision", dep["revision"])
        return {"promoted": True, "revision": dep["revision"], "url": dep["url"]}

    async def monitor(self) -> dict:
        """Watch live traffic for the configured window; auto-rollback on SLO breach."""
        s = self.settings
        url = (await self.hub.call("service_url"))["url"]
        deadline = asyncio.get_event_loop().time() + s.monitor_seconds
        while True:
            hc = await self.hub.call("health_check", url=url, attempts=3)
            errs = (await self.hub.call("error_count", minutes=5))["errors"]
            self.say(f"health_ok={hc['ok']} latency={hc['avg_latency_ms']}ms errors(5m)={errs}")
            if not hc["ok"] or errs > s.max_error_rate:
                prev = (await self.hub.call("previous_revision"))["revision"]
                if prev:
                    await self.hub.call("rollback", revision=prev)
                await self._incident("SLO breach — auto-rollback" if prev else "SLO breach — no rollback target",
                                     {"health": hc, "errors": errs, "rolled_back_to": prev})
                return {"healthy": False, "rolled_back_to": prev}
            if asyncio.get_event_loop().time() >= deadline:
                return {"healthy": True, "errors": errs}
            await asyncio.sleep(s.monitor_interval)

    async def _incident(self, headline: str, data: dict) -> None:
        report = self.llm.ask_json(SYSTEM, f"Headline: {headline}\nData: {data}")
        issue = await self.hub.call("create_issue", title=f"[AutoSRE] {report['title']}",
                                    description=report["body"], labels="autosre,incident")
        self.say(f"Incident filed: {issue['web_url']}")
