FROM python:3.13-bookworm
LABEL org.opencontainers.image.source=https://github.com/vanhansewijck/fpc-dms-ai

# ENV GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no"

WORKDIR /root

# This will install torch with *only* cpu support
# Remove the --extra-index-url part if you want to install all the gpu requirements
# For more details in the different torch distribution visit https://pytorch.org/.
RUN pip install --no-cache-dir docling --extra-index-url https://download.pytorch.org/whl/cpu

# Install application dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables
# ENV HF_HUB_OFFLINE=1
ENV HF_HOME=/tmp/
ENV TORCH_HOME=/tmp/

# Download required models
RUN docling-tools models download

# Copy predownloaded hybrid chunking model to cache
COPY .hybrid-chunk-model/ /tmp/

# Copy application files
COPY bullmq_worker.py ./
COPY process_doc.py ./

# On container environments, always set a thread budget to avoid undesired thread congestion.
ENV OMP_NUM_THREADS=4

# Default path for docling models
ENV DOCLING_ARTIFACTS_PATH=/root/.cache/docling/models


CMD ["python", "-u", "bullmq_worker.py"]