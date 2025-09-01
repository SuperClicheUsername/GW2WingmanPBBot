# Build container
# docker build -t wingmanbot .
# Run container
# docker run --rm -p 5005:5005 -v "%cd%/data:/app/data" --name wingmanbot wingmanbot
FROM python:3.12-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

EXPOSE 5005

# Compiling Python source files to bytecode is typically desirable for production images as it tends to improve startup time (at the cost of increased installation time).
ENV UV_COMPILE_BYTECODE=1
# Silences warnings about not being able to use hard links since the cache and sync target are on separate file systems.
ENV UV_LINK_MODE=copy
# Ensures stdout goes straight to logs in case application crashes.
ENV PYTHONUNBUFFERED=TRUE

WORKDIR /app

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Copy the project into the image
ADD . /app

# Sync the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

CMD ["uv", "run", "hypercorn", "app:app", "-b", "0.0.0.0:5005"]