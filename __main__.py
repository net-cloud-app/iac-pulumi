import pulumi
import pulumi_aws
import pulumi_aws.route53 as route53
from pulumi_aws import ec2, Provider, get_availability_zones, Provider
from pulumi_aws import rds

import pulumi_gcp as gcp
from pulumi_gcp import storage, iam
from pulumi.asset import Archive, FileArchive



# from pulumi_aws_native import rds

import ipaddress
import boto3


print("hi")

aws_profile = pulumi.Config("aws").require("profile")
aws_vpccidr = pulumi.Config("vpc").require("cidrBlock")
aws_region = pulumi.Config("aws").require("region")
key_pair_name = pulumi.Config("vpc").require("ssh_key_pair")
port_no = pulumi.Config("vpc").require("port_no")
host_name=pulumi.Config("host_name").require("name")

# Create a new VPC
vpc = ec2.Vpc("vpc",
              cidr_block=aws_vpccidr,
              enable_dns_support=True,
              enable_dns_hostnames=True,
              tags={
                  "Name": "New_VPC",
              },



              )

# Create a new Internet Gateway and a
#
# ttach it to the VPC
gateway = ec2.InternetGateway("gateway",
                              vpc_id=vpc.id,
                              tags={
                                  "Name": "main-gateway",
                              },

                              )
az_list = pulumi.Config("vpc").require("availabilityZones").split(',')
print(f"inputazs{az_list}")
available_azs = get_availability_zones(state="available").names
print(f"available_azs{available_azs}")

invalid_azs = [az for az in az_list if az not in available_azs]

try:
    if invalid_azs:
        raise ValueError(
            f"Invalid availability zone(s): {', '.join(invalid_azs)}")

    desired_az_count = min(3, len(az_list))
    print(desired_az_count)

    # Calculate subnet CIDR blocks dynamically based on desired AZs
    vpc_cidr = ipaddress.ip_network(aws_vpccidr)
    subnet_cidr_blocks = list(vpc_cidr.subnets(new_prefix=24))[
        :desired_az_count+5]

    # Create a public subnet in each availability zone
    public_subnets = [ec2.Subnet(f"public-subnet-{i+1}",
                                 vpc_id=vpc.id,
                                 cidr_block=str(subnet_cidr_blocks[i]),
                                 map_public_ip_on_launch=True,
                                 availability_zone=az,
                                 tags={
                                     "Name": f"public-subnet-{i+1}",
                                 }
                                 ) for i, az in enumerate(az_list)]

    # Create a private subnet in each availability zone
    private_subnets = [ec2.Subnet(f"private-subnet-{i+1}",
                                  vpc_id=vpc.id,
                                  cidr_block=str(subnet_cidr_blocks[i+4]),
                                  map_public_ip_on_launch=False,
                                  availability_zone=az,
                                  tags={
                                      "Name": f"private-subnet-{i+1}",
                                  }
                                  ) for i, az in enumerate(az_list)]

    private_subnet_ids = [subnet.id for subnet in private_subnets]

    # Create an RDS subnet group
    rds_subnet_group = pulumi_aws.rds.SubnetGroup("my-rds-subnet-group",
                                                  subnet_ids=private_subnet_ids,
                                                  description="Subnet group for RDS instances",
                                                  )

    # Create a public Route Table
    public_route_table = ec2.RouteTable("public-route-table",
                                        vpc_id=vpc.id,
                                        tags={
                                            "Name": "Public Route Table",
                                        }
                                        )

    # Create a private Route Table
    private_route_table = ec2.RouteTable("private-route-table",
                                         vpc_id=vpc.id,
                                         tags={
                                             "Name": "Private Route Table",
                                         }
                                         )

    # Associate public subnets with the public route table
    for i, subnet in enumerate(public_subnets):
        ec2.RouteTableAssociation(f"public-subnet-association-{i}",
                                  subnet_id=subnet.id,
                                  route_table_id=public_route_table.id,
                                  )

    # Associate private subnets with the private route table
    for i, subnet in enumerate(private_subnets):
        ec2.RouteTableAssociation(f"private-subnet-association-{i}",
                                  subnet_id=subnet.id,
                                  route_table_id=private_route_table.id,
                                  )

    # Create a Route in the public route table to direct traffic to the Internet Gateway
    ec2.Route("public-route",
              route_table_id=public_route_table.id,
              destination_cidr_block="0.0.0.0/0",
              gateway_id=gateway.id,  # Connect to the Internet Gateway
              )
    



    # Create the application security group
    app_security_group = ec2.SecurityGroup("app-security-group",
                                           vpc_id=vpc.id,
                                           tags={
                                               "Name": "Application Security Group",
                                           }
                                           )

    app_security_group_rule_ssh = ec2.SecurityGroupRule("app-security-group-rule-ssh",
                                                        type="ingress",
                                                        from_port=22,
                                                        to_port=22,
                                                        protocol="tcp",
                                                        # Allow from anywhere
                                                        cidr_blocks=[
                                                            "0.0.0.0/0"],
                                                        security_group_id=app_security_group.id,
                                                        )
    app_security_group_rule_http = ec2.SecurityGroupRule("app-security-group-rule-http",
                                                         type="ingress",
                                                         from_port=80,
                                                         to_port=80,
                                                         protocol="tcp",
                                                         # Allow from anywhere
                                                         cidr_blocks=[
                                                             "0.0.0.0/0"],
                                                         security_group_id=app_security_group.id,
                                                         )

    app_security_group_rule_https = ec2.SecurityGroupRule("app-security-group-rule-https",
                                                          type="ingress",
                                                          from_port=443,
                                                          to_port=443,
                                                          protocol="tcp",
                                                          # Allow from anywhere
                                                          cidr_blocks=[
                                                              "0.0.0.0/0"],
                                                          security_group_id=app_security_group.id,
                                                          )

    # Replace 'APP_PORT' with your application's specific port
    app_port = port_no
    app_security_group_rule_app = ec2.SecurityGroupRule("app-security-group-rule-app",
                                                        type="ingress",
                                                        from_port=app_port,
                                                        to_port=app_port,
                                                        protocol="tcp",
                                                        # Allow from anywhere
                                                        cidr_blocks=[
                                                            "0.0.0.0/0"],
                                                        security_group_id=app_security_group.id,
                                                        )
    # Your custom AMI name
    # custom_ami_name = "debian12-custom-ami"  # Replace with your AMI name

    # Create an AWS EC2 client using boto3
    ec2_client = boto3.session.Session(profile_name=aws_profile).client("ec2")
    # Use boto3 to search for the custom AMI
    response = ec2_client.describe_images(ExecutableUsers=['self'], Filters=[
                                          {'Name': 'image-type', 'Values': ['machine']}])
    sorted_images = sorted(
        response['Images'], key=lambda x: x['CreationDate'], reverse=True)

    custom_ami_id = 0
    if sorted_images:
        custom_ami_id = sorted_images[0]['ImageId']
        print(f"Latest AMI ID (based on creation time): {custom_ami_id}")
    else:
        print("No AMIs found.")

    if custom_ami_id:
        # The custom AMI was found
        custom_ami_id = custom_ami_id

        outbound_rule = ec2.SecurityGroupRule("outbound-rule",
                                              type="egress",
                                              from_port=3000,
                                              to_port=3000,
                                              protocol="tcp",
                                              cidr_blocks=["0.0.0.0/0"],
                                              security_group_id=app_security_group.id,
                                              )

    else:
        print("Custom AMI not found.")

    # print("this is the RDS instance")
    # Create the RDS security group
    rds_security_group = pulumi_aws.ec2.SecurityGroup("database-security-group",
                                                      vpc_id=vpc.id,  # Replace with your VPC ID
                                                      name="database-security-group",
                                                      description="Security group for RDS instances",
                                                      )

    # Add a rule to allow PostgreSQL traffic from the application security group
    # Assuming you have an `app_security_group` defined elsewhere
    pulumi_aws.ec2.SecurityGroupRule("rds-ingress-rule",
                                     type="ingress",
                                     from_port=3306,
                                     to_port=3306,
                                     protocol="tcp",
                                     security_group_id=rds_security_group.id,
                                     # Replace with your application security group ID
                                     source_security_group_id=app_security_group.id,
                                     )
    
    aws_dev_provider = Provider(
    "awsdev",
    profile=aws_profile,
    region=aws_region,
    )
    
    # sns_topic = pulumi_aws.sns.Topic("my-sns-topic")
    sns_topic = pulumi_aws.sns.Topic(
    "serverlessTopic",
    display_name="Serverless SNS Topic for Lambda Functions",
    )
    

    sns_topic_policy = pulumi_aws.sns.TopicPolicy("my-sns-topic-policy",
    arn=sns_topic.arn,
    policy=pulumi.Output.all(sns_topic.arn).apply(lambda arn: f'''{{
                        "Version": "2012-10-17",
                        "Id": "MySNSTopicPolicy",
                        "Statement": [
                            {{
                                "Effect": "Allow",
                                "Principal": "*",
                                "Action": "SNS:Publish",
                                "Resource": "{arn}",
                                "Condition": {{
                                    "ArnEquals": {{
                                        "aws:SourceArn": "{arn}"
                                    }},
                                    "StringEquals": {{
                                        "SNS:Content-BasedDeduplication": "true"
                                    }}
                                }}
                            }}
                        ]
                    }}''')
                )


    # Creating a custom Parameter group for mariadb
    custom_pg = pulumi_aws.rds.ParameterGroup("csye6255-mariadb",
                                              family="mariadb10.5",
                                              )

# Create an RDS instance with MariaDB
    rds_instance = pulumi_aws.rds.Instance("my-mariadb-instance",
                                           allocated_storage=20,
                                           storage_type="gp2",
                                           engine="mariadb",
                                           engine_version="10.5",
                                           instance_class="db.t3.micro",
                                           parameter_group_name=custom_pg.name,
                                           db_name="csye6225",
                                           username="csye6225",
                                           password="password",
                                           skip_final_snapshot=True,
                                           multi_az=False,
                                           publicly_accessible=False,
                                           # Make sure to define rds_subnet_group
                                           db_subnet_group_name=rds_subnet_group.name,
                                           # Define rds_security_group
                                           vpc_security_group_ids=[
                                               rds_security_group.id],
                                           )
    rds_endpoint = rds_instance.endpoint
    rds_endpoint = rds_endpoint.apply(lambda endpoint: endpoint.split(":")[
                                      0] if ":" in endpoint else endpoint)
    db_name = rds_instance.db_name
    db_username = rds_instance.username
    db_password = rds_instance.password
    sns_arn = sns_topic.arn

    user_data = pulumi.Output.all(rds_endpoint, db_name, db_username, db_password, sns_arn).apply(
        lambda args: f"""#!/bin/bash
echo "DB_ENDPOINT={args[0]}" > /opt/csye6225/.env
echo "DB_USERNAME={args[1]}" >> /opt/csye6225/.env
echo "DB_DATABASE={args[2]}" >> /opt/csye6225/.env
echo "DB_PASSWORD={args[3]}" >> /opt/csye6225/.env
echo "SNS_TOPIC_ARN={args[4]}" >> /opt/csye6225/.env


sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/opt/csye6225/amazon-cloudwatch-agent.json -s

"""

    )

    # ec2_role = pulumi_aws.iam.Role('ec2Role',
    #                                assume_role_policy="""{
    #         "Version": "2012-10-17",
    #         "Statement": [{
    #             "Action": "sts:AssumeRole",
    #             "Effect": "Allow",
    #             "Principal": {
    #                 "Service": "ec2.amazonaws.com"
    #             }
    #         }]
    #     }"""
    #                                )
    # # Attach the AWS-managed CloudWatchAgentServer policy to the role
    # policy_attachment = pulumi_aws.iam.RolePolicyAttachment('CloudWatchAgentServerPolicyAttachment',
    #                                                         role=ec2_role.name,
    #                                                         policy_arn='arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy')

    # Create an Instance Profile for the role
    # instance_profile = pulumi_aws.iam.InstanceProfile(
    #     'ec2InstanceProfile', role=ec2_role.name)

    config = pulumi.Config()

    # Get values from Pulumi Config
    gcp_project = config.require("gcpProject")
    email_server = config.require("emailServer")
    email_port = config.require("emailPort")
    email_username = config.require("emailUsername")
    email_password = config.require_secret("emailPassword")

    # Google Cloud Storage bucket
    bucket = gcp.storage.Bucket("my-bucket", location="us")

    # Google Service Account
    service_account = gcp.serviceaccount.Account("my-service-account",
        account_id="my-service-account",
        display_name="My Service Account",
        project=gcp_project,  # Use Pulumi Config for project ID
    )



    access_key = gcp.serviceaccount.Key("my-service-account-key",
        service_account_id=service_account.id,
    )

    storage_admin_binding = gcp.projects.IAMMember(
        "storage-admin-binding",
        project=gcp_project,
        member=pulumi.Output.concat("serviceAccount:", service_account.email),
        role="roles/storage.objectAdmin",
    ) 

#  Create an AWS Secrets Manager secret with a new unique name

    # secNameforgcpkeys = pulumi_aws.secretsmanager.Secret(
    #     "secNameforgcpkeys",
    #     name="secNameforgcpkeys",  # Replace with your new unique secret name
    #     description="Google Cloud service account key for Lambda",
    # )


# Use the private key and service account id directly, without marking them as secrets
    access_key_secret = access_key.private_key
    secret_id = service_account.id

    # DynamoDB instancez
    table = pulumi_aws.dynamodb.Table("my-table",
    
        attributes=[
            {
                "name": "Id",
                "type": "N",
            },
        ],
        hash_key="Id",
        read_capacity=5,
        write_capacity=5,
    )

    # IAM Role for Lambda Function
    role = pulumi_aws.iam.Role("my-role",
        assume_role_policy="""{
        "Version": "2012-10-17",
        "Statement": [
            {
            "Action": "sts:AssumeRole",
            "Principal": {
                "Service": "lambda.amazonaws.com"
            },
            "Effect": "Allow",
            "Sid": ""
            }
        ]
        }"""
    )

    # lambda_zip_path = '/Users/harish/Downloads/dependency/lamdacode.zip'
    # lambda_zip = FileArchive(lambda_zip_path)

# AWS Lambda function
    lambda_func = pulumi_aws.lambda_.Function("my-lambda",
        code=pulumi.AssetArchive({
            ".": pulumi.FileArchive("dependency"),
        }),  # Replace with your Lambda code path
        handler="index.handler",
        runtime="nodejs14.x",
        environment=pulumi_aws.lambda_.FunctionEnvironmentArgs(
            variables={
                "GOOGLE_CREDENTIALS": access_key_secret,
                "EMAIL_SERVER": email_server,
                "EMAIL_PORT": email_port,
                "EMAIL_USERNAME": email_username,
                "EMAIL_PASSWORD": email_password,
                "GOOGLE_PROJECT_ID": secret_id,
                "GCS_BUCKET_NAME": bucket.name,  # Export GCS_BUCKET_NAME
                "DYNAMODB_TABLE_NAME": table.name,  # Export DYNAMODB_TABLE_NAME
            },
        ),
        role=role.arn,
    )

    sns_subscription = pulumi_aws.sns.TopicSubscription(
        "snsToLambda",
        topic=sns_topic.arn,
        protocol="lambda",
        endpoint=lambda_func.arn,
        opts=pulumi.ResourceOptions(provider=aws_dev_provider),
    )

    lambda_permission = pulumi_aws.lambda_.Permission(
        "lambdaPermission",
        action="lambda:InvokeFunction",
        function=lambda_func.name,
        principal="sns.amazonaws.com",
        source_arn=sns_topic.arn,
        opts=pulumi.ResourceOptions(provider=aws_dev_provider),
    )

    pulumi.export("lambda_permission_id", lambda_permission.id)


    pulumi.export("sns_subscription_id", sns_subscription.id)

    # IAM Policy for Lambda Function
    policy = pulumi_aws.iam.Policy("my-policy",
        policy="""{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": [
                    "logs:*"
                ],
                "Effect": "Allow",
                "Resource": "*"
            }
        ]
    }"""
    )

    sns_publish_policy = pulumi_aws.iam.Policy(
        "sns-publish-policy",
        name="sns-publish-policy",
        description="Allows publishing to SNS topics",
        policy={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "sns:Publish",
                    "Resource": "*",
                },
            ],
        },
    )

# ec2_role = pulumi_aws.iam.Role('ec2Role',
#                                    assume_role_policy="""{
#             "Version": "2012-10-17",
#             "Statement": [{
#                 "Action": "sts:AssumeRole",
#                 "Effect": "Allow",
#                 "Principal": {
#                     "Service": "ec2.amazonaws.com"
#                 }
#             }]
#         }"""

    ec2_role = pulumi_aws.iam.Role(
        "cloudwatch-agent-role",
        assume_role_policy="""{
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "sts:AssumeRole",
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "ec2.amazonaws.com"
                    }
                }
            ]
        }""",
        managed_policy_arns=[
            "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
            sns_publish_policy.arn,  # Replace "sns_publish_policy" with the actual reference to your SNS publishing policy
        ],
    )
                                   
    # Attach the AWS-managed CloudWatchAgentServer policy to the role
    policy_attachment = pulumi_aws.iam.RolePolicyAttachment('CloudWatchAgentServerPolicyAttachment',
                                                                role=ec2_role.name,
                                                                policy_arn='arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy')

# Attach the policy to the role
# policy_attachment = pulumi_aws.iam.RolePolicyAttachment("my-policy-attachment",
#     role=role.name,
#     policy_arn=policy.arn,
# )

    sns_policy_attachment = pulumi_aws.iam.RolePolicyAttachment(
        "sns-publish-policy-attachment",
        role=ec2_role.name,  # Replace "role" with the actual name or reference to your IAM role
        policy_arn=sns_publish_policy.arn,  # Replace "sns_publish_policy" with the actual reference to your SNS publishing policy
    )

    instance_profile = pulumi_aws.iam.InstanceProfile(
            'ec2InstanceProfile', role=ec2_role.name)



    pulumi.export("bucket_name", bucket.name)
    pulumi.export("dynamodb_table_name", table.name)
    pulumi.export("email_username", email_username)
    pulumi.export("email_password", email_password)


    # Export values
    pulumi.export("bucket_name", bucket.name)
    pulumi.export("service_account_email", service_account.email)
    pulumi.export("public_key", access_key.public_key)
    # pulumi.export_secret("access_key_secret", access_key_secret)
    pulumi.export("access_key_secret", access_key_secret)


    ec2_instance = ec2.Instance("ec2-instance",
                                    ami=custom_ami_id,
                                    instance_type="t2.micro",
                                    subnet_id=public_subnets[0].id,
                                    security_groups=[app_security_group.id],
                                    key_name=key_pair_name,  # Attach the key pair
                                    iam_instance_profile=instance_profile.name,

                                    associate_public_ip_address=True,
                                    tags={
                                        "Name": "MyEC2Instance",
                                    },
                                    root_block_device=ec2.InstanceRootBlockDeviceArgs(
                                        volume_size=25,
                                        volume_type='gp2',
                                        delete_on_termination=True,
                                    ),
                                    disable_api_termination=False,
                                    user_data=user_data
                                    )
    ec2.SecurityGroupRule("ec2-to-rds-outbound-rule",
                            type="egress",
                            from_port=3306,             # Source port
                            to_port=3306,               # Destination port
                            protocol="tcp",
                            # Reference to the RDS security group
                            source_security_group_id=rds_security_group.id,
                            # Your EC2 instance's security group ID
                            security_group_id=app_security_group.id
                            )

    ec2.SecurityGroupRule("ec2-to-internet-https-outbound-rule",
                            type="egress",
                            from_port=443,               # Source port for HTTPS
                            to_port=443,                 # Destination port for HTTPS
                            protocol="tcp",
                            # Allow to all IP addresses
                            cidr_blocks=["0.0.0.0/0"],
                            # Your EC2 instance's security group ID
                            security_group_id=app_security_group.id
                            )


except ValueError as e:
        # Handle the exception
    print(f"An error occurred: {e}")
    pulumi.export('vpc_id', vpc.id)

# ----new code-----




route53_client = boto3.client("route53")

domain_name = host_name  # Replace with your domain name

# Get the hosted zone ID dynamically based on the domain name
route53_zone = pulumi_aws.route53.get_zone(name=domain_name)

# Create an A record to point to your EC2 instance's public IP address
a_record = pulumi_aws.route53.Record("my-a-record",
                                     name=domain_name,  # Root context
                                     zone_id=route53_zone.id,
                                     type="A",
                                     ttl=300,
                                     # Assuming ec2_instance is your EC2 resource
                                     records=[ec2_instance.public_ip],
                                     )


# config = pulumi.Config()

# # Get values from Pulumi Config
# gcp_project = config.require("gcpProject")
# email_server = config.require("emailServer")
# email_port = config.require("emailPort")
# email_username = config.require("emailUsername")
# email_password = config.require_secret("emailPassword")

# # Google Cloud Storage bucket
# bucket = gcp.storage.Bucket("my-bucket", location="us")

# # Google Service Account
# service_account = gcp.serviceaccount.Account("my-service-account",
#     account_id="my-service-account",
#     display_name="My Service Account",
#     project=gcp_project,  # Use Pulumi Config for project ID
# )



# access_key = gcp.serviceaccount.Key("my-service-account-key",
#     service_account_id=service_account.id,
# )

# storage_admin_binding = gcp.projects.IAMMember(
#     "storage-admin-binding",
#     project=gcp_project,
#     member=pulumi.Output.concat("serviceAccount:", service_account.email),
#     role="roles/storage.objectAdmin",
# ) 

# #  Create an AWS Secrets Manager secret with a new unique name

# secNameforgcpkeys = pulumi_aws.secretsmanager.Secret(
#     "secNameforgcpkeys",
#     name="secNameforgcpkeys",  # Replace with your new unique secret name
#     description="Google Cloud service account key for Lambda",
# )


# # Use the private key and service account id directly, without marking them as secrets
# access_key_secret = access_key.private_key
# secret_id = service_account.id

# # DynamoDB instancez
# table = pulumi_aws.dynamodb.Table("my-table",
 
#     attributes=[
#         {
#             "name": "Id",
#             "type": "N",
#         },
#     ],
#     hash_key="Id",
#     read_capacity=5,
#     write_capacity=5,
# )

# # IAM Role for Lambda Function
# role = pulumi_aws.iam.Role("my-role",
#     assume_role_policy="""{
#       "Version": "2012-10-17",
#       "Statement": [
#         {
#           "Action": "sts:AssumeRole",
#           "Principal": {
#             "Service": "lambda.amazonaws.com"
#           },
#           "Effect": "Allow",
#           "Sid": ""
#         }
#       ]
#     }"""
# )

# lambda_zip_path = '/Users/ankithreddy/Desktop/cloud/Nov22/lambda.zip'
# lambda_zip = FileArchive(lambda_zip_path)

# # AWS Lambda function
# lambda_func = pulumi_aws.lambda_.Function("my-lambda",
#     code=pulumi.AssetArchive({
#         ".": pulumi.FileArchive("lambda_zip"),
#     }),  # Replace with your Lambda code path
#     handler="index.handler",
#     runtime="nodejs14.x",
#     environment=pulumi_aws.lambda_.FunctionEnvironmentArgs(
#         variables={
#             "GOOGLE_CREDENTIALS": access_key_secret,
#             "EMAIL_SERVER": email_server,
#             "EMAIL_PORT": email_port,
#             "EMAIL_USERNAME": email_username,
#             "EMAIL_PASSWORD": email_password,
#             "GOOGLE_PROJECT_ID": secret_id,
#             "GCS_BUCKET_NAME": bucket.name,  # Export GCS_BUCKET_NAME
#             "DYNAMODB_TABLE_NAME": table.name,  # Export DYNAMODB_TABLE_NAME
#         },
#     ),
#     role=role.arn,
# )

# sns_subscription = pulumi_aws.sns.TopicSubscription(
#     "snsToLambda",
#     topic=sns_topic.arn,
#     protocol="lambda",
#     endpoint=lambda_func.arn,
#     opts=pulumi.ResourceOptions(provider=aws_dev_provider),
# )

# lambda_permission = pulumi_aws.lambda_.Permission(
#     "lambdaPermission",
#     action="lambda:InvokeFunction",
#     function=lambda_func.name,
#     principal="sns.amazonaws.com",
#     source_arn=sns_topic.arn,
#     opts=pulumi.ResourceOptions(provider=aws_dev_provider),
# )

# pulumi.export("lambda_permission_id", lambda_permission.id)


# pulumi.export("sns_subscription_id", sns_subscription.id)

# # IAM Policy for Lambda Function
# policy = pulumi_aws.iam.Policy("my-policy",
#     policy="""{
#     "Version": "2012-10-17",
#     "Statement": [
#         {
#             "Action": [
#                 "logs:*"
#             ],
#             "Effect": "Allow",
#             "Resource": "*"
#         }
#     ]
# }"""
# )

# sns_publish_policy = pulumi_aws.iam.Policy(
#     "sns-publish-policy",
#     name="sns-publish-policy",
#     description="Allows publishing to SNS topics",
#     policy={
#         "Version": "2012-10-17",
#         "Statement": [
#             {
#                 "Effect": "Allow",
#                 "Action": "sns:Publish",
#                 "Resource": "*",
#             },
#         ],
#     },
# )

# # ec2_role = pulumi_aws.iam.Role('ec2Role',
# #                                    assume_role_policy="""{
# #             "Version": "2012-10-17",
# #             "Statement": [{
# #                 "Action": "sts:AssumeRole",
# #                 "Effect": "Allow",
# #                 "Principal": {
# #                     "Service": "ec2.amazonaws.com"
# #                 }
# #             }]
# #         }"""

# ec2_role = pulumi_aws.iam.Role(
#     "cloudwatch-agent-role",
#     assume_role_policy="""{
#         "Version": "2012-10-17",
#         "Statement": [
#             {
#                 "Action": "sts:AssumeRole",
#                 "Effect": "Allow",
#                 "Principal": {
#                     "Service": "ec2.amazonaws.com"
#                 }
#             }
#         ]
#     }""",
#     managed_policy_arns=[
#         "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
#         sns_publish_policy.arn,  # Replace "sns_publish_policy" with the actual reference to your SNS publishing policy
#     ],
# )
                                   
#     # Attach the AWS-managed CloudWatchAgentServer policy to the role
# policy_attachment = pulumi_aws.iam.RolePolicyAttachment('CloudWatchAgentServerPolicyAttachment',
#                                                             role=ec2_role.name,
#                                                             policy_arn='arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy')

# # Attach the policy to the role
# # policy_attachment = pulumi_aws.iam.RolePolicyAttachment("my-policy-attachment",
# #     role=role.name,
# #     policy_arn=policy.arn,
# # )

# sns_policy_attachment = iam.RolePolicyAttachment(
#     "sns-publish-policy-attachment",
#     role=ec2_role.name,  # Replace "role" with the actual name or reference to your IAM role
#     policy_arn=sns_publish_policy.arn,  # Replace "sns_publish_policy" with the actual reference to your SNS publishing policy
# )

# instance_profile = pulumi_aws.iam.InstanceProfile(
#         'ec2InstanceProfile', role=ec2_role.name)



# pulumi.export("bucket_name", bucket.name)
# pulumi.export("dynamodb_table_name", table.name)
# pulumi.export("email_username", email_username)
# pulumi.export("email_password", email_password)


# # Export values
# pulumi.export("bucket_name", bucket.name)
# pulumi.export("service_account_email", service_account.email)
# pulumi.export("public_key", access_key.public_key)
# # pulumi.export_secret("access_key_secret", access_key_secret)
# pulumi.export("access_key_secret", access_key_secret)




# Export your EC2 instance's public IP and the Route 53 A record
pulumi.export("ec2_instance_public_ip", ec2_instance.public_ip)
pulumi.export("route53_a_record", a_record.fqdn)
pulumi.export("sns_topic_arn", sns_topic.arn)
pulumi.export("topicName", sns_topic.name)



