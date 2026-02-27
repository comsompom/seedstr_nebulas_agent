from __future__ import annotations

import argparse
import logging
from pathlib import Path

from dotenv import set_key

from .api import SeedstrApiClient, SeedstrApiError
from .config import load_settings


def setup_logger(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    return logging.getLogger("seedstr-agent")


def _persist_env_key(env_path: Path, key: str, value: str) -> None:
    if not env_path.exists():
        env_path.write_text("", encoding="utf-8")
    set_key(str(env_path), key, value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seedstr Python agent")
    sub = parser.add_subparsers(dest="command", required=True)

    register_parser = sub.add_parser("register", help="Register agent and save API key to .env")
    register_parser.add_argument("--wallet", help="Solana wallet address")
    register_parser.add_argument("--owner-url", help="Owner URL (optional)")

    sub.add_parser("verify", help="Trigger Seedstr verification check")
    sub.add_parser("me", help="Show current agent profile info")
    sub.add_parser("status", help="Show quick readiness status")
    profile_parser = sub.add_parser("profile", help="Update profile fields")
    profile_parser.add_argument("--name", help="Display name")
    profile_parser.add_argument("--bio", help="Short bio")
    profile_parser.add_argument("--picture", help="Profile picture URL")
    skills_parser = sub.add_parser("skills", help="Update skills list")
    skills_parser.add_argument(
        "--set",
        required=True,
        help='Comma-separated skills, example: "python,solana,llm,automation"',
    )
    sub.add_parser("skills-list", help="List available Seedstr skills")
    prepare_parser = sub.add_parser("prepare", help="Apply defaults and print verification instructions")
    prepare_parser.add_argument("--name", default="Nebulas Multi-Model Agent")
    prepare_parser.add_argument(
        "--bio",
        default=(
            "Autonomous multi-model agent for Seedstr. "
            "Uses Gemini and OpenAI with automatic failover for resilient responses."
        ),
    )
    prepare_parser.add_argument(
        "--skills",
        default="Research,API Integration,Data Analysis,Technical Writing,Web Scraping,Code Review",
    )
    sub.add_parser("run", help="Run the polling loop forever")
    sub.add_parser("once", help="Run one polling cycle and exit")

    args = parser.parse_args()
    settings = load_settings()
    logger = setup_logger(settings.log_level)
    api = SeedstrApiClient(
        base_url=settings.seedstr_base_url,
        api_key=settings.seedstr_api_key,
        timeout_seconds=settings.request_timeout_seconds,
    )

    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"

    if args.command == "register":
        wallet = (args.wallet or settings.solana_wallet_address).strip()
        if not wallet:
            raise SystemExit("Wallet address is required. Use --wallet or set SOLANA_WALLET_ADDRESS.")
        owner_url = args.owner_url or settings.seedstr_owner_url
        try:
            data = api.register(wallet, owner_url)
            api_key = str(data.get("apiKey", "")).strip()
            agent_id = str(data.get("agentId", "")).strip()
            if api_key:
                _persist_env_key(env_path, "SEEDSTR_API_KEY", api_key)
                logger.info("Registration successful. API key saved to %s", env_path)
            else:
                logger.warning("Registered but no apiKey found in response")
            logger.info("Agent ID: %s", agent_id or "(not returned)")
        except SeedstrApiError as exc:
            logger.error("Registration failed: %s", exc)
            raise SystemExit(1) from exc
        return

    if not settings.seedstr_api_key:
        raise SystemExit("SEEDSTR_API_KEY is required for this command. Run register first.")

    if args.command == "verify":
        try:
            data = api.verify()
            logger.info("Verify response: %s", data)
        except SeedstrApiError as exc:
            logger.error("Verify failed: %s", exc)
            raise SystemExit(1) from exc
        return

    if args.command == "me":
        try:
            data = api.get_me()
            logger.info("Agent profile: %s", data)
        except SeedstrApiError as exc:
            logger.error("Could not fetch profile: %s", exc)
            raise SystemExit(1) from exc
        return

    if args.command == "status":
        try:
            me = api.get_me()
            verification = me.get("verification", {})
            logger.info("Agent ID: %s", me.get("id", "(unknown)"))
            logger.info("Name: %s", me.get("name", "(unset)"))
            logger.info("Verified: %s", verification.get("isVerified"))
            logger.info("Jobs completed: %s", me.get("jobsCompleted", 0))
            if verification.get("verificationInstructions"):
                logger.info("Verification instructions:\n%s", verification["verificationInstructions"])
        except SeedstrApiError as exc:
            logger.error("Status check failed: %s", exc)
            raise SystemExit(1) from exc
        return

    if args.command == "profile":
        if not any([args.name, args.bio, args.picture]):
            raise SystemExit("Provide at least one field: --name, --bio, --picture")
        try:
            result = api.update_profile(
                name=args.name,
                bio=args.bio,
                profile_picture=args.picture,
            )
            logger.info("Profile updated: %s", result)
        except SeedstrApiError as exc:
            logger.error("Profile update failed: %s", exc)
            raise SystemExit(1) from exc
        return

    if args.command == "skills":
        skills = [item.strip() for item in args.set.split(",") if item.strip()]
        if not skills:
            raise SystemExit("No valid skills found in --set")
        try:
            result = api.update_skills(skills)
            logger.info("Skills updated: %s", result)
        except SeedstrApiError as exc:
            logger.error("Skills update failed: %s", exc)
            raise SystemExit(1) from exc
        return

    if args.command == "skills-list":
        try:
            data = api.list_skills()
            logger.info("Available skills: %s", data)
        except SeedstrApiError as exc:
            logger.error("Could not list skills: %s", exc)
            raise SystemExit(1) from exc
        return

    if args.command == "prepare":
        try:
            api.update_profile(name=args.name, bio=args.bio)
            skills = [item.strip() for item in args.skills.split(",") if item.strip()]
            if skills:
                try:
                    api.update_skills(skills)
                except SeedstrApiError as skills_error:
                    logger.warning("Skills not updated: %s", skills_error)
            me = api.get_me()
            verification = me.get("verification", {})
            logger.info("Preparation completed.")
            logger.info("Agent ID: %s", me.get("id", "(unknown)"))
            logger.info("Current name: %s", me.get("name", "(unset)"))
            logger.info("Current skills: %s", me.get("skills", []))
            logger.info("Verified: %s", verification.get("isVerified"))
            if verification.get("verificationInstructions"):
                logger.info("Tweet this for verification:\n%s", verification["verificationInstructions"])
        except SeedstrApiError as exc:
            logger.error("Prepare failed: %s", exc)
            raise SystemExit(1) from exc
        return

    from .runner import AgentRunner

    runner = AgentRunner(settings=settings, logger=logger)
    if args.command == "once":
        runner.run_once()
    elif args.command == "run":
        runner.run_forever()


if __name__ == "__main__":
    main()

