from __future__ import annotations

from backend.knowledge import (
    KnowledgeItemType,
    KnowledgeWorkspaceService,
    SqliteKnowledgeRepository,
)
from backend.knowledge.board_repository import SqliteKnowledgeBoardRepository
from backend.knowledge.board_service import KnowledgeBoardService


def _services(tmp_path):
    path = tmp_path / "knowledge_workspace.sqlite3"
    workspace = KnowledgeWorkspaceService(SqliteKnowledgeRepository(path))
    boards = KnowledgeBoardService(SqliteKnowledgeBoardRepository(path), workspace)
    return workspace, boards


def test_board_nodes_survive_restart_and_keep_geometry(tmp_path) -> None:
    workspace, boards = _services(tmp_path)
    item = workspace.create_item(item_type=KnowledgeItemType.PAPER, title="Paper")
    board = boards.ensure_default_board()
    boards.upsert_node(
        board_id=board.board_id,
        item_id=item.item_id,
        x=120.5,
        y=-48.0,
        width=310.0,
        height=188.0,
        z_index=4,
    )

    reopened_workspace, reopened_boards = _services(tmp_path)
    assert reopened_workspace.get_item(item.item_id) is not None
    node = reopened_boards.list_nodes(board.board_id)[0]
    assert (node.x, node.y) == (120.5, -48.0)
    assert (node.width, node.height) == (310.0, 188.0)
    assert node.z_index == 4


def test_same_knowledge_item_can_appear_on_multiple_boards(tmp_path) -> None:
    workspace, boards = _services(tmp_path)
    item = workspace.create_item(item_type=KnowledgeItemType.CONCEPT, title="Safe BO")
    first = boards.ensure_default_board()
    second = boards.create_board(name="PID Research")

    boards.upsert_node(board_id=first.board_id, item_id=item.item_id, x=0, y=0)
    boards.upsert_node(board_id=second.board_id, item_id=item.item_id, x=500, y=240)

    assert boards.list_nodes(first.board_id)[0].item_id == item.item_id
    assert boards.list_nodes(second.board_id)[0].item_id == item.item_id
    assert workspace.list_items() == [item]


def test_removing_board_node_does_not_delete_knowledge_item(tmp_path) -> None:
    workspace, boards = _services(tmp_path)
    item = workspace.create_item(item_type=KnowledgeItemType.NOTE, title="Note")
    board = boards.ensure_default_board()
    boards.upsert_node(board_id=board.board_id, item_id=item.item_id, x=20, y=30)

    assert boards.remove_node(board_id=board.board_id, item_id=item.item_id) is True
    assert boards.list_nodes(board.board_id) == []
    assert workspace.get_item(item.item_id) == item
