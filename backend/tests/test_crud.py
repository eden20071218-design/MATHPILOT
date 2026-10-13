from datetime import datetime, timezone


def create_student(client, email="student@example.com"):
    response = client.post(
        "/api/v1/students",
        json={"email": email, "display_name": "Student", "timezone": "Asia/Shanghai"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_knowledge_point(client, code):
    response = client.post(
        "/api/v1/knowledge-points",
        json={"code": code, "name": code, "subject": "mathematics"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_student_crud_and_unique_email(client):
    student = create_student(client)
    fetched = client.get(f"/api/v1/students/{student['id']}")
    assert fetched.status_code == 200

    updated = client.patch(
        f"/api/v1/students/{student['id']}", json={"display_name": "Updated"}
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Updated"

    duplicate = client.post(
        "/api/v1/students",
        json={"email": student["email"], "display_name": "Duplicate"},
    )
    assert duplicate.status_code == 409

    deleted = client.delete(f"/api/v1/students/{student['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/students/{student['id']}").status_code == 404


def test_question_can_link_multiple_knowledge_points(client):
    kp1 = create_knowledge_point(client, "ALG.LINEAR")
    kp2 = create_knowledge_point(client, "ALG.EQUATION")
    question = client.post(
        "/api/v1/questions", json={"stem": "Solve 2x + 1 = 5", "difficulty": 0.3}
    ).json()

    for index, kp in enumerate((kp1, kp2)):
        response = client.post(
            "/api/v1/question-knowledge-points",
            json={
                "question_id": question["id"],
                "knowledge_point_id": kp["id"],
                "weight": 0.5,
                "is_primary": index == 0,
            },
        )
        assert response.status_code == 201, response.text

    links = client.get("/api/v1/question-knowledge-points").json()
    assert len(links) == 2
    assert {link["knowledge_point_id"] for link in links} == {kp1["id"], kp2["id"]}


def test_student_mastery_history_is_preserved(client):
    student = create_student(client)
    kp = create_knowledge_point(client, "CALC.LIMIT")
    timestamps = ["2026-10-01T10:00:00Z", "2026-10-08T10:00:00Z"]
    for mastery, recorded_at in zip((0.35, 0.62), timestamps):
        response = client.post(
            "/api/v1/student-knowledge-states",
            json={
                "student_id": student["id"],
                "knowledge_point_id": kp["id"],
                "mastery": mastery,
                "confidence": 0.7,
                "recorded_at": recorded_at,
            },
        )
        assert response.status_code == 201, response.text

    states = client.get("/api/v1/student-knowledge-states").json()
    assert len(states) == 2
    assert {float(state["mastery"]) for state in states} == {0.35, 0.62}


def test_foreign_key_and_composite_unique_constraints(client):
    student = create_student(client)
    exam_payload = {
        "student_id": student["id"],
        "title": "Midterm",
        "version": 1,
        "total_score": 100,
        "status": "draft",
    }
    assert client.post("/api/v1/exams", json=exam_payload).status_code == 201
    assert client.post("/api/v1/exams", json=exam_payload).status_code == 409

    invalid = client.post(
        "/api/v1/exams",
        json={**exam_payload, "title": "Invalid", "student_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert invalid.status_code == 409

