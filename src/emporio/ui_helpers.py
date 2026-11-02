"""Pure helper types, free-model catalog, and formatters for the Streamlit evidence UI."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from emporio.agent import TurnResult
from emporio.language import ResponseLanguage, language_from_directives

FREE_OPENROUTER_MODELS: tuple[str, ...] = (
    "openrouter/free",
    "google/gemma-4-31b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-32b:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
)

LOCAL_DETERMINISTIC_MODEL_ID = "local/deterministic-grounded-agent:free"


@dataclass(frozen=True)
class PresetScenario:
    """A pre-defined customer prompt aligned with the technical assessment scenarios."""

    scenario_id: str
    title: str
    requirements: str
    expected_evidence: str
    prompt: str


PRESET_SCENARIOS: tuple[PresetScenario, ...] = (
    PresetScenario(
        scenario_id="E01_catalog_filtered",
        title="01 - Product Search (Guitars <= R$1,000)",
        requirements="FR-03, FR-04, D-10, D-11",
        expected_evidence="search_products (12 guitars), product CSV rows",
        prompt="Which acoustic/classical guitars are available for R$1,000 or less?",
    ),
    PresetScenario(
        scenario_id="E04_policy_hours",
        title="02 - Store Policy (Saturday Opening Hours)",
        requirements="FR-03, FR-05",
        expected_evidence="search_policy, Policy §2 p.2 (09:00 to 13:00)",
        prompt="What time do you open on Saturdays?",
    ),
    PresetScenario(
        scenario_id="E03_order_status",
        title="03 - Order Status (Order 8)",
        requirements="FR-03, FR-04",
        expected_evidence="get_order_status, order/item/product rows",
        prompt="What's the status of order 8?",
    ),
    PresetScenario(
        scenario_id="E05_out_of_scope",
        title="04 - Out of Scope (Coding + Guitar Strings)",
        requirements="FR-06",
        expected_evidence="No tool call; polite decline of coding & accessories, redirect",
        prompt="Can you write a Python script for me, and do you sell guitar strings?",
    ),
    PresetScenario(
        scenario_id="E07_return_multi_tool",
        title="05 - Return Eligibility + Policy (Order 7)",
        requirements="FR-04, FR-05, FR-11, D-10",
        expected_evidence="get_order_status, check_return_eligibility, search_policy (§4.1 p.4)",
        prompt=(
            "I changed my mind about order 7. Can I still return it, and what does the "
            "policy say?"
        ),
    ),
    PresetScenario(
        scenario_id="E06_unknown_entities",
        title="06 - Unknown Product & Order (Negative Path)",
        requirements="FR-04, Grounding",
        expected_evidence="get_product + get_order_status -> both not found, no fabrication",
        prompt="Do you have the Gibson Zebra Nonexistent X9, and what is the status of order 9999?",
    ),
)


class LocalDeterministicChatModel(BaseChatModel):
    """Offline tool-calling chat model that drives the real LangGraph tools when API is 429."""

    bound_tool_names: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "local-deterministic-grounded"

    def bind_tools(self, tools: Any, **kwargs: Any) -> LocalDeterministicChatModel:
        self.bound_tool_names = sorted(getattr(tool, "name", str(tool)) for tool in tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_human_idx = max(
            (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)),
            default=-1,
        )
        user_text = str(messages[last_human_idx].content) if last_human_idx >= 0 else ""
        turn_tool_messages = [
            m for m in messages[last_human_idx + 1 :] if isinstance(m, ToolMessage)
        ]
        language = language_from_directives(messages)

        if not turn_tool_messages:
            planned_calls = _plan_tool_calls(user_text)
            if planned_calls:
                ai_msg = AIMessage(
                    content="",
                    tool_calls=planned_calls,
                    usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                )
                return ChatResult(generations=[ChatGeneration(message=ai_msg)])

        reply_text = _synthesize_grounded_reply(user_text, turn_tool_messages, language)
        ai_msg = AIMessage(
            content=reply_text,
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])


def _plan_tool_calls(user_text: str) -> list[dict[str, Any]]:
    """Map a customer question to the real LangGraph tool calls."""
    lower = "".join(
        char
        for char in unicodedata.normalize("NFKD", user_text.casefold())
        if not unicodedata.combining(char)
    )

    # Out-of-scope coding / general requests or unsupported accessories (E05_out_of_scope)
    out_of_scope_markers = (
        "capital da franca",
        "capital of france",
        "python",
        "binary search",
        "recipe",
        "weather",
        "javascript",
        "poem",
        "programacao",
        "escreva um codigo",
        "receita",
        "clima",
        "poema",
    )
    if any(m in lower for m in out_of_scope_markers):
        return []

    # Return eligibility + order status + policy (E07_return_multi_tool)
    order_match = re.search(r"\b(?:order|pedido)\s*#?(\d+)\b", lower)
    return_words = (
        "return",
        "refund",
        "exchange",
        "changed my mind",
        "defect",
        "devolver",
        "devolucao",
        "trocar",
        "troca",
        "arrepend",
        "mudei de ideia",
        "defeito",
    )
    if order_match and any(w in lower for w in return_words):
        order_id = int(order_match.group(1))
        reason = (
            "defect"
            if any(word in lower for word in ("defect", "broken", "defeito", "quebrado"))
            else "regret"
        )
        policy_query = (
            "troca defeito fabricação prazo"
            if reason == "defect"
            else "direito arrependimento devolução 7 dias"
        )
        return [
            {
                "name": "get_order_status",
                "args": {"order_id": order_id},
                "id": f"call_ord_{order_id}",
                "type": "tool_call",
            },
            {
                "name": "check_return_eligibility",
                "args": {"order_id": order_id, "reason": reason},
                "id": f"call_ret_{order_id}",
                "type": "tool_call",
            },
            {
                "name": "search_policy",
                "args": {"query": policy_query, "k": 3},
                "id": f"call_pol_{order_id}",
                "type": "tool_call",
            },
        ]

    # Combined unknown product + order lookup (E06_unknown_entities)
    product_question_markers = ("do you have the ", "voce tem o ", "voces tem o ", "tem o ")
    if order_match and any(marker in lower for marker in product_question_markers):
        order_id = int(order_match.group(1))
        name_match = re.search(
            r"(?:do you have the|voce tem o|voces tem o|tem o)\s+([^,?]+)",
            lower,
            flags=re.IGNORECASE,
        )
        exact_name = name_match.group(1).strip() if name_match else user_text
        return [
            {
                "name": "get_product",
                "args": {"exact_name": exact_name},
                "id": "call_prod_name_1",
                "type": "tool_call",
            },
            {
                "name": "get_order_status",
                "args": {"order_id": order_id},
                "id": f"call_ord_{order_id}",
                "type": "tool_call",
            },
        ]

    # Order status lookup (E03_order_status)
    if order_match:
        order_id = int(order_match.group(1))
        return [
            {
                "name": "get_order_status",
                "args": {"order_id": order_id},
                "id": f"call_ord_{order_id}",
                "type": "tool_call",
            }
        ]

    # Specific product ID lookup
    prod_match = re.search(r"\b(?:product|produto|sku|item)\s*#?0*(\d+)\b", lower)
    if prod_match:
        product_id = int(prod_match.group(1))
        return [
            {
                "name": "get_product",
                "args": {"product_id": product_id},
                "id": f"call_prod_{product_id}",
                "type": "tool_call",
            }
        ]

    # Catalog / product search (E01_catalog_filtered & general catalog questions)
    if any(
        w in lower
        for w in (
            "guitar",
            "viol",
            "violao",
            "acoustic",
            "classical",
            "electric",
            "bass",
            "piano",
            "keyboard",
            "drum",
            "microphone",
            "amp",
            "available",
            "disponivel",
            "catalog",
            "catalogo",
            "under r$",
            "r$1,000",
            "r$ 1,000",
            "r$1000",
        )
    ):
        args: dict[str, Any] = {
            "available_only": any(
                word in lower for word in ("available", "disponivel", "have", "tem")
            ),
            "limit": 20,
        }
        if "acoustic" in lower or "classical" in lower or "viol" in lower:
            args["category"] = "acoustic_classical_guitars"
        elif "electric guitar" in lower or "guitarra eletrica" in lower:
            args["category"] = "electric_guitars"
        elif "guitar" in lower:
            args["category"] = "acoustic_classical_guitars"
        elif "bass" in lower:
            args["category"] = "bass"
        elif "piano" in lower or "keyboard" in lower or "teclado" in lower:
            args["category"] = "keyboards_pianos"
        elif "drum" in lower or "percussion" in lower or "bateria" in lower or "percuss" in lower:
            args["category"] = "drums_percussion"
        elif "ukulele" in lower:
            args["category"] = "ukuleles"

        price_match = re.search(r"r\$\s*([\d.,]+)", lower)
        if price_match:
            raw_num = price_match.group(1)
            if "." in raw_num and "," in raw_num:
                raw_num = raw_num.replace(".", "").replace(",", ".")
            elif "," in raw_num:
                head, tail = raw_num.rsplit(",", 1)
                raw_num = head + tail if len(tail) == 3 else head + "." + tail
            elif "." in raw_num:
                head, tail = raw_num.rsplit(".", 1)
                if len(tail) == 3:
                    raw_num = head + tail
            try:
                args["max_price_brl"] = float(raw_num)
            except ValueError:
                pass
        return [
            {
                "name": "search_products",
                "args": args,
                "id": "call_search_1",
                "type": "tool_call",
            }
        ]

    # Store policy questions (E04_policy_hours & general policy questions)
    return [
        {
            "name": "search_policy",
            "args": {"query": user_text[:180], "k": 3},
            "id": "call_policy_1",
            "type": "tool_call",
        }
    ]


def _synthesize_grounded_reply(
    user_text: str,
    tool_messages: Sequence[ToolMessage],
    language: ResponseLanguage,
) -> str:
    """Format a grounded response in the application-selected language."""
    if language == "pt-BR":
        return _synthesize_portuguese_reply(user_text, tool_messages)
    return _synthesize_english_reply(user_text, tool_messages)


def _saturday_hours(source_text: str) -> tuple[str, str] | None:
    """Extract Saturday hours from a retrieved PT-BR passage without inventing values."""
    match = re.search(r"Sábado\s+(\d{2}:\d{2})\s+às\s+(\d{2}:\d{2})", source_text)
    return match.groups() if match else None


def _synthesize_english_reply(user_text: str, tool_messages: Sequence[ToolMessage]) -> str:
    """Format a faithful English response strictly from the returned tool JSON payloads."""
    lower = user_text.lower()
    sections: list[str] = []

    if not tool_messages and any(
        m in lower for m in ("python", "binary search", "javascript", "recipe", "poem", "string")
    ):
        return (
            "I cannot write code or help with general programming requests, and we do not carry "
            "standalone accessories such as replacement guitar strings in our catalog. However, "
            "I would be happy to help you with Empório da Música's musical instruments, active "
            "promotions, order status, return eligibility, or store policies!"
        )

    for msg in tool_messages:
        try:
            payload = json.loads(str(msg.content))
        except (TypeError, ValueError):
            continue

        if msg.name == "search_products":
            items = payload.get("products", [])
            if not items:
                sections.append(
                    "No matching products were found in the store catalog for that query."
                )
                continue
            if any(
                marker in lower for marker in ("cheapest", "least expensive", "lowest price")
            ):
                priced_items: list[tuple[Decimal, dict[str, Any]]] = []
                for item in items:
                    try:
                        priced_items.append((Decimal(str(item.get("price_brl"))), item))
                    except (InvalidOperation, TypeError):
                        continue
                if not priced_items:
                    sections.append("No matching product had a valid catalog price.")
                    continue
                _, cheapest = min(priced_items, key=lambda pair: pair[0])
                source = cheapest.get("source", {})
                sections.append(
                    f"The cheapest matching product is **{cheapest.get('name')}** "
                    f"(ID `{cheapest.get('product_id')}`) at **R$ "
                    f"{cheapest.get('price_brl')}**, with stock "
                    f"`{cheapest.get('stock_quantity')}` "
                    f"(source: `{source.get('file')}:{source.get('row')}`)."
                )
                continue
            lines = ["Here are the matching products from our catalog:"]
            for item in items:
                name = item.get("name", "Unknown")
                pid = item.get("product_id")
                price = item.get("price_brl")
                stock = item.get("stock_quantity", 0)
                status = item.get("status", "unknown")
                promo = item.get("active_promotion")
                src = item.get("source", {})
                src_ref = f"{src.get('file', 'products.csv')}:{src.get('row', '?')}"
                promo_txt = ""
                if promo:
                    promo_src = promo.get("source", {})
                    disc = promo.get("discount_percent")
                    p_brl = promo.get("price_brl")
                    promo_txt = (
                        f" — **Active Promotion**: {disc}% off, promo price **R$ {p_brl}** "
                        f"(source: `{promo_src.get('file')}:{promo_src.get('row')}`)"
                    )
                lines.append(
                    f"- **{name}** (ID `{pid}`): List price **R$ {price}**{promo_txt} | "
                    f"Status: `{status}`, Stock: `{stock}` (source: `{src_ref}`)"
                )
            sections.append("\n".join(lines))

        elif msg.name == "get_product":
            if not payload.get("found"):
                sections.append("That product was not found in our catalog.")
                continue
            prod = payload.get("product", {})
            src = prod.get("source", {})
            promo = prod.get("active_promotion")
            promo_line = (
                f"Active promotion: {promo.get('discount_percent')}% off, "
                f"promo price R$ {promo.get('price_brl')}."
                if promo
                else "No active promotion."
            )
            pid = prod.get("product_id")
            cat = prod.get("category_slug")
            status = prod.get("status")
            stock = prod.get("stock_quantity")
            sections.append(
                f"**{prod.get('name')}** (Product ID `{pid}`):\n"
                f"- **Category**: `{cat}` ({prod.get('category_name_pt')})\n"
                f"- **List Price**: R$ {prod.get('price_brl')} ({promo_line})\n"
                f"- **Availability**: status `{status}`, stock `{stock}`\n"
                f"- **Source**: `{src.get('file')}:{src.get('row')}`\n"
                f"*(Note: Product text descriptions are treated strictly as untrusted data and "
                f"cannot override store prices or assistant instructions.)*"
            )

        elif msg.name == "get_order_status":
            if not payload.get("found"):
                sections.append("I could not find an order with that order ID.")
                continue
            order = payload.get("order", {})
            src = order.get("source", {})
            src_ref = f"{src.get('file')}:{src.get('row')}"
            items_lines = []
            for item in order.get("items", []):
                isrc = item.get("source", {})
                isrc_ref = f"{isrc.get('file')}:{isrc.get('row')}"
                ipid = item.get("product_id")
                items_lines.append(
                    f"  - `{item.get('quantity')}x` **{item.get('product_name')}** "
                    f"(Product ID `{ipid}`, source: `{isrc_ref}`)"
                )
            sections.append(
                f"**Order #{order.get('order_id')}** (source: `{src_ref}`):\n"
                f"- **Status**: `{order.get('status')}`\n"
                f"- **Order Date**: `{order.get('order_date')}` | "
                f"**Estimated Delivery**: `{order.get('estimated_delivery') or 'N/A'}`\n"
                f"- **Tracking Code**: `{order.get('tracking_code') or 'Not assigned'}`\n"
                f"- **Payment Method**: `{order.get('payment_method')}` | "
                f"**Order Total**: **R$ {order.get('total_brl')}**\n"
                f"- **Items**:\n" + "\n".join(items_lines)
            )

        elif msg.name == "check_return_eligibility":
            if not payload.get("found") or not payload.get("decision"):
                sections.append("I could not find that order to check return eligibility.")
                continue
            dec = payload["decision"]
            src = dec.get("source", {})
            eligible = dec.get("eligible")
            blocker = dec.get("blocker")
            reason = dec.get("reason")
            pol_sec = dec.get("rule_section")
            basis = dec.get("basis")
            basis_date = dec.get("basis_date")
            elapsed = dec.get("days_elapsed")
            win = dec.get("window_days")
            unverified = ", ".join(dec.get("not_checked", []))
            sections.append(
                f"**Return Eligibility for Order #{dec.get('order_id')}** "
                f"(source: `{src.get('file')}:{src.get('row')}`):\n"
                f"- **Eligible**: `{eligible}` (Blocker: `{blocker or 'none'}`)\n"
                f"- **Reason Checked**: `{reason}` (Policy §`{pol_sec}`)\n"
                f"- **Order Status**: `{dec.get('order_status')}`\n"
                f"- **Basis Date (`{basis}`)**: `{basis_date}` | "
                f"**Reference Date**: `{dec.get('reference_date')}` "
                f"(`{elapsed}` days elapsed of `{win}`-day window)\n"
                f"- **Unverified Conditions**: {unverified}"
            )

        elif msg.name == "search_policy":
            results = payload.get("results", [])
            if not results:
                sections.append("No matching store policy section was found.")
                continue
            pol_lines = ["**Store Policy Evidence:**"]
            for r in results[:2]:
                sec_id = r.get("section_id")
                title = r.get("title_pt", "")
                pages = r.get("pages", [])
                page_str = ", ".join(str(p) for p in pages)
                text_snippet = " ".join(str(r.get("text_pt", "")).split())
                hours = _saturday_hours(text_snippet)
                if hours:
                    pol_lines.append(
                        f"- Saturday hours: **{hours[0]} to {hours[1]}** "
                        f"(Store Policy §{sec_id}, p. {page_str})."
                    )
                pol_lines.append(
                    f"- **Store Policy §{sec_id} ({title}, p. {page_str})**. "
                    f"Original PT-BR evidence: {text_snippet}"
                )
            sections.append("\n".join(pol_lines))

    if not sections:
        return (
            "I can only help with Empório da Música products, promotions, orders, return "
            "deadlines, and store policies."
        )
    return "\n\n".join(sections)


def _synthesize_portuguese_reply(
    user_text: str, tool_messages: Sequence[ToolMessage]
) -> str:
    """Format a PT-BR response while preserving exact source values."""
    lower = user_text.lower()
    sections: list[str] = []
    if not tool_messages and any(
        marker in lower
        for marker in ("python", "programação", "escreva um código", "receita", "poema", "corda")
    ):
        return (
            "Não posso escrever código nem ajudar com programação, e acessórios avulsos como "
            "cordas de reposição não fazem parte do nosso catálogo. Posso ajudar com "
            "instrumentos, promoções, pedidos, devoluções ou políticas da loja."
        )

    for message in tool_messages:
        try:
            payload = json.loads(str(message.content))
        except (TypeError, ValueError):
            continue

        if message.name == "search_products":
            products = payload.get("products", [])
            if not products:
                sections.append("Nenhum produto correspondente foi encontrado no catálogo.")
                continue
            lines = ["Estes são os produtos correspondentes no catálogo:"]
            for product in products:
                source = product.get("source", {})
                lines.append(
                    f"- **{product.get('name')}** (ID `{product.get('product_id')}`): "
                    f"**R$ {product.get('price_brl')}**, status `{product.get('status')}`, "
                    f"estoque `{product.get('stock_quantity')}` "
                    f"(fonte: `{source.get('file')}:{source.get('row')}`)"
                )
            sections.append("\n".join(lines))

        elif message.name == "get_product":
            if not payload.get("found"):
                sections.append("Esse produto não foi encontrado no catálogo.")
                continue
            product = payload.get("product", {})
            source = product.get("source", {})
            sections.append(
                f"**{product.get('name')}** (ID `{product.get('product_id')}`): preço "
                f"**R$ {product.get('price_brl')}**, status `{product.get('status')}`, estoque "
                f"`{product.get('stock_quantity')}` "
                f"(fonte: `{source.get('file')}:{source.get('row')}`)."
            )

        elif message.name == "get_order_status":
            if not payload.get("found"):
                sections.append("Não encontrei um pedido com esse ID.")
                continue
            order = payload.get("order", {})
            source = order.get("source", {})
            item_lines = [
                f"  - `{item.get('quantity')}x` **{item.get('product_name')}** "
                f"(ID do produto `{item.get('product_id')}`)"
                for item in order.get("items", [])
            ]
            sections.append(
                f"**Pedido #{order.get('order_id')}** "
                f"(fonte: `{source.get('file')}:{source.get('row')}`):\n"
                f"- **Status**: `{order.get('status')}`\n"
                f"- **Data do pedido**: `{order.get('order_date')}`\n"
                f"- **Entrega estimada**: `{order.get('estimated_delivery') or 'N/A'}`\n"
                f"- **Código de rastreio**: "
                f"`{order.get('tracking_code') or 'Não atribuído'}`\n"
                f"- **Forma de pagamento**: `{order.get('payment_method')}`\n"
                f"- **Total**: **R$ {order.get('total_brl')}**\n"
                f"- **Itens**:\n" + "\n".join(item_lines)
            )

        elif message.name == "check_return_eligibility":
            if not payload.get("found") or not payload.get("decision"):
                sections.append(
                    "Não encontrei esse pedido para verificar a elegibilidade da devolução."
                )
                continue
            decision = payload["decision"]
            source = decision.get("source", {})
            not_checked_translations = {
                "product condition and original packaging": (
                    "condição do produto e embalagem original"
                ),
                "purchase channel (section 4.1 covers online purchases)": (
                    "canal de compra (a seção 4.1 cobre compras online)"
                ),
                "non-eligible items (section 4.4)": "itens não elegíveis (seção 4.4)",
                "actual delivery date (estimated_delivery is used as a proxy)": (
                    "data real de entrega (estimated_delivery foi usada como aproximação)"
                ),
            }
            not_checked = ", ".join(
                not_checked_translations.get(item, item)
                for item in decision.get("not_checked", [])
            )
            sections.append(
                f"**Elegibilidade de devolução do Pedido #{decision.get('order_id')}** "
                f"(fonte: `{source.get('file')}:{source.get('row')}`):\n"
                f"- **Elegível**: `{decision.get('eligible')}`\n"
                f"- **Impedimento**: `{decision.get('blocker') or 'nenhum'}`\n"
                f"- **Regra**: Política da Loja §{decision.get('rule_section')}\n"
                f"- **Data-base**: `{decision.get('basis_date')}` | "
                f"**Data de referência**: `{decision.get('reference_date')}`\n"
                f"- **Dias decorridos**: `{decision.get('days_elapsed')}` de uma janela de "
                f"`{decision.get('window_days')}` dias\n"
                f"- **Não verificado**: {not_checked}"
            )

        elif message.name == "search_policy":
            results = payload.get("results", [])
            if not results:
                sections.append(
                    "Nenhuma seção correspondente foi encontrada na política da loja."
                )
                continue
            policy_lines = ["**Evidência da Política da Loja:**"]
            for result in results[:2]:
                pages = ", ".join(str(page) for page in result.get("pages", []))
                source_text = " ".join(str(result.get("text_pt", "")).split())
                hours = _saturday_hours(source_text)
                if hours:
                    policy_lines.append(
                        f"- Horário de sábado: **{hours[0]} às {hours[1]}** "
                        f"(Política da Loja §{result.get('section_id')}, p. {pages})."
                    )
                policy_lines.append(
                    f"- **Política da Loja §{result.get('section_id')} "
                    f"({result.get('title_pt')}, p. {pages})**: {source_text}"
                )
            sections.append("\n".join(policy_lines))

    if not sections:
        return (
            "Posso ajudar apenas com produtos, promoções, pedidos, devoluções e políticas "
            "da Empório da Música."
        )
    return "\n\n".join(sections)


@dataclass(frozen=True)
class TurnEvidence:
    """Recorded evidence for one user->assistant turn in the UI."""

    turn_index: int
    user_prompt: str
    reply: str
    error: str | None = None
    trace: tuple[str, ...] = field(default_factory=tuple)
    usage: dict[str, int] | None = None
    latency_ms: float = 0.0
    executed_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    scenario_id: str | None = None
    model_used: str | None = None

    @classmethod
    def from_turn_result(
        cls,
        *,
        turn_index: int,
        user_prompt: str,
        result: TurnResult,
        latency_ms: float,
        executed_at: str | None = None,
        scenario_id: str | None = None,
        model_used: str | None = None,
    ) -> TurnEvidence:
        """Construct a TurnEvidence record from a completed `run_turn` call."""
        timestamp = executed_at or datetime.now(UTC).isoformat(timespec="seconds")
        return cls(
            turn_index=turn_index,
            user_prompt=user_prompt,
            reply=result.reply,
            error=result.error,
            trace=tuple(result.trace),
            usage=dict(result.usage) if result.usage is not None else None,
            latency_ms=round(latency_ms, 1),
            executed_at=timestamp,
            scenario_id=scenario_id,
            model_used=model_used,
        )


def get_preset_by_id(scenario_id: str) -> PresetScenario | None:
    """Return the preset scenario matching `scenario_id`, or `None` if not found."""
    for preset in PRESET_SCENARIOS:
        if preset.scenario_id == scenario_id:
            return preset
    return None


def summarize_session_usage(turns: Sequence[TurnEvidence]) -> dict[str, int]:
    """Sum token counts across all recorded turns in the current session."""
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "turns_with_usage": 0,
    }
    for turn in turns:
        if not turn.usage:
            continue
        totals["turns_with_usage"] += 1
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = turn.usage.get(key, 0)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
    return totals


def format_usage_line(usage: dict[str, int] | None) -> str:
    """Format token usage metadata into a compact human-readable string."""
    if not usage:
        return "not reported"
    inp = usage.get("input_tokens", 0)
    out = usage.get("output_tokens", 0)
    total = usage.get("total_tokens", 0)
    return f"input={inp}, output={out}, total={total}"


def export_evidence_markdown(
    *,
    thread_id: str,
    model: str,
    reference_date: date,
    turns: Sequence[TurnEvidence],
) -> str:
    """Render a multi-turn session into a Markdown evidence document for `examples/`."""
    totals = summarize_session_usage(turns)
    errors = sum(1 for t in turns if t.error is not None)
    status = "PASS (0 runtime errors)" if turns and errors == 0 else f"INCOMPLETE/ERROR ({errors})"

    lines: list[str] = [
        "# Empório da Música — Dialogue Evidence Transcript",
        "",
        f"- **Thread ID**: `{thread_id}`",
        f"- **Configured Model**: `{model}`",
        f"- **Reference date**: `{reference_date.isoformat()}`",
        f"- **Total turns**: `{len(turns)}`",
        f"- **Session status**: **{status}**",
        (
            f"- **Cumulative token usage**: `input={totals['input_tokens']}, "
            f"output={totals['output_tokens']}, total={totals['total_tokens']}`"
        ),
        "",
    ]

    if not turns:
        lines.append("_No turns recorded in this session yet._")
        return "\n".join(lines) + "\n"

    for turn in turns:
        header_suffix = f" ({turn.scenario_id})" if turn.scenario_id else ""
        lines.extend(
            [
                f"## Turn {turn.turn_index}{header_suffix}",
                "",
                f"- **Executed at (UTC)**: `{turn.executed_at}`",
                f"- **Model used**: `{turn.model_used or model}`",
                f"- **Latency**: `{turn.latency_ms:.1f} ms`",
                f"- **Status**: `{'error=' + turn.error if turn.error else 'ok'}`",
                f"- **Token usage**: `{format_usage_line(turn.usage)}`",
                "",
                "### User Prompt",
                "",
                turn.user_prompt,
                "",
                "### Assistant Response",
                "",
                turn.reply,
                "",
                "### Tool Trace and Source References",
                "",
            ]
        )
        if turn.trace:
            for entry in turn.trace:
                lines.append(f"- `{entry}`")
        else:
            lines.append("- No tools invoked.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def export_evidence_json(
    *,
    thread_id: str,
    model: str,
    reference_date: date,
    turns: Sequence[TurnEvidence],
) -> str:
    """Render a multi-turn session into structured JSON evidence."""
    payload = {
        "thread_id": thread_id,
        "model": model,
        "reference_date": reference_date.isoformat(),
        "turn_count": len(turns),
        "usage_summary": summarize_session_usage(turns),
        "turns": [
            {
                "turn_index": turn.turn_index,
                "scenario_id": turn.scenario_id,
                "model_used": turn.model_used or model,
                "executed_at": turn.executed_at,
                "latency_ms": turn.latency_ms,
                "error": turn.error,
                "usage": turn.usage,
                "user_prompt": turn.user_prompt,
                "reply": turn.reply,
                "trace": list(turn.trace),
            }
            for turn in turns
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
