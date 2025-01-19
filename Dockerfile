FROM docker.io/python:3.13-alpine

RUN pip3 install poetry

WORKDIR /app

COPY . .
RUN poetry install

ENTRYPOINT ["poetry", "run"]
CMD ["bot"]

