FROM python:3.14-slim


RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

ADD https://astral.sh/uv/install.sh /uv-installer.sh

RUN sh /uv-installer.sh && rm /uv-installer.sh

ENV PATH="/root/.local/bin/:$PATH"

WORKDIR /

COPY pyproject.toml uv.lock* ./

RUN uv sync --locked

COPY . .

CMD ["uv", "run", "python", "-m", "app.main"]
