"""Hash map and trie for the same frequencies. The request reads a stored top 10. It does not sort."""

from __future__ import annotations

TOP = 10


def rank(items: list[tuple[str, int]]) -> list[dict]:
    ordered = sorted(items, key=lambda item: (-item[1], item[0]))[:TOP]
    return [{"text": text, "frequency": freq} for text, freq in ordered]


class TrieNode:
    def __init__(self) -> None:
        self.children: dict[str, TrieNode] = {}
        self.top: list[tuple[str, int]] = []

    def offer(self, text: str, freq: int) -> None:
        self.top.append((text, freq))
        self.top.sort(key=lambda item: (-item[1], item[0]))
        del self.top[TOP:]


class SuggestionIndex:
    def __init__(self, freq: dict[str, int]) -> None:
        self.hash_map: dict[str, list[dict]] = {}
        self.root = TrieNode()
        buckets: dict[str, list[tuple[str, int]]] = {"": []}
        for text, count in freq.items():
            if count <= 0 or not text:
                continue
            buckets[""].append((text, count))
            node = self.root
            node.offer(text, count)
            prefix = ""
            for ch in text:
                prefix += ch
                buckets.setdefault(prefix, []).append((text, count))
                node = node.children.setdefault(ch, TrieNode())
                node.offer(text, count)
        self.hash_map = {prefix: rank(items) for prefix, items in buckets.items()}
        self.prefix_count = len(self.hash_map)

    def lookup(self, prefix: str, limit: int) -> dict:
        stored = self.hash_map.get(prefix, [])
        steps = []
        node = self.root
        if prefix == "":
            steps.append({"char": "(root)", "stored": rank(node.top)})
        else:
            for ch in prefix:
                node = node.children.get(ch) if node else None
                steps.append({
                    "char": ch,
                    "stored": rank(node.top) if node else [],
                })
        trie_list = steps[-1]["stored"] if steps else []
        return {
            "suggestions": stored[:limit],
            "hashMap": {"prefix": prefix, "stored": stored},
            "trie": {"steps": steps, "stored": trie_list[:limit]},
            "same": [row["text"] for row in stored[:limit]] == [row["text"] for row in trie_list[:limit]],
        }
