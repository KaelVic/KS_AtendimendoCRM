#!/usr/bin/env bash
set -Eeuo pipefail

# Read-only verification. It never creates, updates, downloads, or deletes
# resources. No bucket names, object keys, or volume IDs are printed.
: "${BACKUP_S3_URI:?BACKUP_S3_URI is required}"
: "${BACKUP_STAMP:?BACKUP_STAMP is required}"
: "${EBS_VOLUME_ID:?EBS_VOLUME_ID is required}"

if [[ ! "$BACKUP_S3_URI" =~ ^s3://([^/]+)/(.+)$ ]]; then
  echo 'Refusing verification: BACKUP_S3_URI must be s3://bucket/prefix.' >&2
  exit 2
fi
BUCKET="${BASH_REMATCH[1]}"
PREFIX="${BASH_REMATCH[2]%/}"
OBJECT_PREFIX="${PREFIX}/${BACKUP_STAMP}"

ebs_encrypted="$(aws ec2 describe-volumes --volume-ids "$EBS_VOLUME_ID" \
  --query 'Volumes[0].Encrypted' --output text)"
if [[ "$ebs_encrypted" != "True" ]]; then
  echo 'Storage verification failed: EBS is not encrypted.' >&2
  exit 1
fi

bucket_algorithm="$(aws s3api get-bucket-encryption --bucket "$BUCKET" \
  --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' \
  --output text)"
if [[ "$bucket_algorithm" != "AES256" && "$bucket_algorithm" != "aws:kms" ]]; then
  echo 'Storage verification failed: bucket default encryption is not enabled.' >&2
  exit 1
fi

object_algorithm="$(aws s3api head-object --bucket "$BUCKET" \
  --key "${OBJECT_PREFIX}/SHA256SUMS" --query 'ServerSideEncryption' --output text)"
if [[ "$object_algorithm" != "AES256" && "$object_algorithm" != "aws:kms" ]]; then
  echo 'Storage verification failed: backup object is not encrypted.' >&2
  exit 1
fi

printf 'storage_encryption=verified ebs=true bucket=true backup_object=true\n'
