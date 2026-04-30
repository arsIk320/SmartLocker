import argparse
from pathlib import Path

from app.database import Base, SessionLocal, engine
from app.schemas import DomainList
from app.services.health import system_health
from app.services.links import build_vless_url
from app.services.users import create_user, delete_user, get_user, list_users
from app.services.xray import ensure_runtime_files, read_domains, sync_xray, write_domains


def init_runtime(initial_user: str | None) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_runtime_files()
    db = SessionLocal()
    try:
        if initial_user and not list_users(db):
            create_user(db, initial_user)
        sync_xray(db)
    finally:
        db.close()


def cmd_add_user(args: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        user = create_user(db, args.name)
        sync_xray(db)
        print(f"UUID: {user.uuid}")
        print(f"LINK: {build_vless_url(user.uuid, user.name)}")
    finally:
        db.close()


def cmd_remove_user(args: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        deleted = delete_user(db, args.uuid)
        if not deleted:
            raise SystemExit("user not found")
        sync_xray(db)
        print(f"Removed: {args.uuid}")
    finally:
        db.close()


def cmd_list_users(_: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        for user in list_users(db):
            print(f"{user.uuid}\t{user.name}\t{build_vless_url(user.uuid, user.name)}")
    finally:
        db.close()


def cmd_show_link(args: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        user = get_user(db, args.uuid)
        if user is None:
            raise SystemExit("user not found")
        print(build_vless_url(user.uuid, user.name))
    finally:
        db.close()


def cmd_set_domains(args: argparse.Namespace) -> None:
    write_domains(args.domain)
    db = SessionLocal()
    try:
        sync_xray(db)
    finally:
        db.close()
    print(f"Saved {len(read_domains())} domain(s) into {Path('/etc/xray/domains.json')}")


def cmd_list_domains(_: argparse.Namespace) -> None:
    payload = DomainList(domains=read_domains())
    for domain in payload.domains:
        print(domain)


def cmd_status(_: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        status = system_health(db)
    finally:
        db.close()
    for key, value in status.items():
        print(f"{key}: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xray-manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--initial-user", default=None)
    init_parser.set_defaults(func=lambda args: init_runtime(args.initial_user))

    add_parser = subparsers.add_parser("add-user")
    add_parser.add_argument("--name", required=True)
    add_parser.set_defaults(func=cmd_add_user)

    remove_parser = subparsers.add_parser("remove-user")
    remove_parser.add_argument("--uuid", required=True)
    remove_parser.set_defaults(func=cmd_remove_user)

    list_parser = subparsers.add_parser("list-users")
    list_parser.set_defaults(func=cmd_list_users)

    link_parser = subparsers.add_parser("show-link")
    link_parser.add_argument("--uuid", required=True)
    link_parser.set_defaults(func=cmd_show_link)

    domains_parser = subparsers.add_parser("set-domains")
    domains_parser.add_argument("--domain", action="append", required=True)
    domains_parser.set_defaults(func=cmd_set_domains)

    list_domains_parser = subparsers.add_parser("list-domains")
    list_domains_parser.set_defaults(func=cmd_list_domains)

    status_parser = subparsers.add_parser("status")
    status_parser.set_defaults(func=cmd_status)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
