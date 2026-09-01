
# Architecture Specification Draft: ImageNetOG Redux

## 1. Cloud Infrastructure and IaC Target

* **Provisioning Framework**: Terraform
* **Cloud Provider**: AWS
* **Deployment Region**: us-east-1
* **Environment**: Development, Staging, Production


## 2. GLobal System Boundary & Network Topology

* **Ingress**: AWS API Gateway
* **API Authorization**: AWS Cognito JWT Authorizer

## 3. Component Architecture Map

### 3.1. API Ingress & Compute Layer [COMPUTE-01]
* **Resource Type:** AWS Lambda Functions
* **Runtime Environment:** Latest Python 3.x
* **Integration Pattern:** Proxy integration with API Gateway REST/HTTP API.
* **Authentication/Authorization:** AWS Cognito User Pools / Custom Lambda Authorizer

### 3.2. Raw Image Storage Layer [STORAGE-01]
* **Resource Type:** AWS S3 Buckets
* **Storage Class:** S3 Standard
* **Access Control:** IAM roles for Lambda functions (read, signed url generation), S3 bucket policies for public access prevention, IAM admin role permissions allowing images to be added to buckets.

### 3.3 Vector Embedding Storage Layer [STORAGE-02]
* **Resource Type:** S3Vector Bucket

### 3.4. Vector Embedding Generation Layer [COMPUTE-02]
* **Resource Type:** AWS Lambda Functions
* **Runtime Environment:** Latest Python 3.x

### 3.5. Image Upload Orchestration Layer [COMPUTE-03]
* **Resource Type:** AWS Step Functions

### 3.6. Metadata Storage Layer [STORAGE-03]
* **Resource Type:** AWS DynamoDB Table(s) to store collection and image metadata, including collection name, creation date, S3 bucket location, and S3Vector bucket location.


## 4. Image Administration

Image administration will be done via the AWS CLI and/or AWS Management Console, with a dedicated IAM role assigned to users performing administration functions.

The following administrative functions will be supported:

* **Collection Management**: Administrators can create collections. A collection consists of an s3 bucket, a corresponding vector embedding bucket, and a DynamoDB table entry that contains the collection name, creation date, and location of the s3 bucket and s3vector bucket. The administrator creates the two buckets and inserts the entry into the DynamoDB table. A standard naming convention will be used for the buckets and DynamoDB table entry to ensure consistency and ease of management. A script will be provided that takes the collection name as input and creates the two buckets and inserts the entry into the DynamoDB table. The script will also ensure that the naming convention is followed and that the buckets and DynamoDB table entry are created in the correct region.

* **Image Upload**: Administrators can upload images to the S3 bucket using the AWS CLI or Management Console. The system will automatically trigger the a workflow to do the following:
    * Generate a vector embedding for the image using a low-cost pre-trained bedrock model and store it in the corresponding S3Vector bucket, along with metadata to support date and other filtering operations needed for end user API access.
    * Generate a description of the image using a low-cost pre-trained bedrock model.
    * Store the image metadata, including the image key, date added, description, and location of the S3 bucket and S3Vector bucket in DynamoDB.

## 5. Image Search

When searching for images in a collection using a description provided by the user, the system will perform a vector search using the S3Vector bucket to find images that are similar to the provided description. The system will return a list of images that match the search criteria, along with their keys, dates added, and descriptions. The user can then retrieve a specific image in the collection by providing its key, and the system will return a temporary URL to the image file, valid for a limited time (e.g., 5 minutes). The system will ensure that the temporary URL is secure and cannot be used to access the image after it expires.