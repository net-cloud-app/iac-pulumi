import pulumi
import pulumi_aws
import pulumi_aws.route53 as route53
from pulumi_aws import ec2, Provider, get_availability_zones, Provider
from pulumi_aws import rds
from pulumi_aws import autoscaling
from pulumi_aws import lb

# from pulumi_aws_native import rds

import ipaddress
import boto3
import base64




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
# Attach it to the VPC
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
    public_subnet_ids = [subnet.id for subnet in public_subnets]

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
    
    load_balancer_security_group = ec2.SecurityGroup("load-balancer-security-group",
                                            vpc_id=vpc.id,
                                            tags={
                                                "Name": "Load Balancer Security Group",
                                            }
                                            )
    
    load_balancer_sg_id = load_balancer_security_group.id

    
  

    load_balancer_security_group_rule_80 = ec2.SecurityGroupRule("load-balancer-ingress-rule-80",
                                            type="ingress",
                                            from_port=80,
                                            to_port=80,
                                            protocol="tcp",
                                            cidr_blocks=["0.0.0.0/0"],  # Allow from anywhere
                                            security_group_id=load_balancer_security_group.id,
                                            )
    

    load_balancer_security_group_rule_443 = ec2.SecurityGroupRule("load-balancer-ingress-rule-443",
                                            type="ingress",
                                            from_port=443,
                                            to_port=443,
                                            protocol="tcp",
                                            cidr_blocks=["0.0.0.0/0"],  # Allow from anywhere
                                            security_group_id=load_balancer_security_group.id,
                                        )
    
    pulumi_aws.ec2.SecurityGroupRule("load-balancer-egress-rule",
                                        type="egress",
                                        from_port=0,
                                        to_port=0,
                                        protocol="-1",
                                        cidr_blocks=["0.0.0.0/0"],  # Allow to anywhere
                                        security_group_id=load_balancer_security_group.id,
                                    )
    

    app_security_group_rule_ssh = ec2.SecurityGroupRule("app-security-group-rule-ssh",
                                                        type="ingress",
                                                        from_port=22,
                                                        to_port=22,
                                                        protocol="tcp",
                                                        # Allow from anywhere
                                                        cidr_blocks=[
                                                              "0.0.0.0/0"],
                                                        security_group_id=load_balancer_security_group.id,
                                                        )
    
    app_port = port_no
    # app_security_group_rule_app = ec2.SecurityGroupRule("app-security-group-rule-app",
    #                                                     type="ingress",
    #                                                     from_port=app_port,
    #                                                     to_port=app_port,
    #                                                     protocol="tcp",
    #                                                     # Allow from anywhere
    #                                                     cidr_blocks=[
    #                                                         "0.0.0.0/0"],
    #                                                     security_group_id=load_balancer_security_group.id,
    #                                                     )
    
    ec2.SecurityGroupRule("app-from-lb",
        type="ingress",
        from_port=8000,
        to_port=8000,
        protocol="tcp",
        source_security_group_id=load_balancer_sg_id,
        security_group_id=app_security_group.id,
    )
    

    ec2.SecurityGroupRule("app-security-group-egress-rule",
                                type="egress",
                                from_port=0,
                                to_port=0,
                                protocol="-1",
                                # Allow all outbound traffic only to the load balancer security group
                                security_group_id=app_security_group.id,
                                source_security_group_id=load_balancer_security_group.id,
                            )

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

    # Create the RDS security group
    rds_security_group = pulumi_aws.ec2.SecurityGroup("database-security-group",
                                                      vpc_id=vpc.id,  
                                                      name="database-security-group",
                                                      description="Security group for RDS instances",
                                                      )


    pulumi_aws.ec2.SecurityGroupRule("rds-ingress-rule",
                                     type="ingress",
                                     from_port=3306,
                                     to_port=3306,
                                     protocol="tcp",
                                     security_group_id=rds_security_group.id,
                                     source_security_group_id=app_security_group.id,
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
                                           db_subnet_group_name=rds_subnet_group.name,
                                           vpc_security_group_ids=[
                                               rds_security_group.id],
                                           )
    rds_endpoint = rds_instance.endpoint
    rds_endpoint = rds_endpoint.apply(lambda endpoint: endpoint.split(":")[
                                      0] if ":" in endpoint else endpoint)
    db_name = rds_instance.db_name
    db_username = rds_instance.username
    db_password = rds_instance.password

    user_data = pulumi.Output.all(rds_endpoint, db_name, db_username, db_password).apply(
        lambda args: f"""#!/bin/bash
echo "DB_ENDPOINT={args[0]}" > /opt/csye6225/.env
echo "DB_USERNAME={args[1]}" >> /opt/csye6225/.env
echo "DB_DATABASE={args[2]}" >> /opt/csye6225/.env
echo "DB_PASSWORD={args[3]}" >> /opt/csye6225/.env

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/opt/csye6225/amazon-cloudwatch-agent.json -s

sudo chown root:root /opt/csye6225/migrations/20231001203320-create-assignment.js

cd /opt/csye6225
node app.js

"""

    )

    def encoding(data):
        return base64.b64encode(data.encode()).decode()

    encoded_userdata = user_data.apply(encoding)

    # Create the Application Load Balancer
    load_balancer = pulumi_aws.lb.LoadBalancer("web-app-lb",
                                        enable_deletion_protection=False,
                                        internal=False,
                                        load_balancer_type="application",
                                        # security_groups=[app_security_group.id],  # Attach the load balancer security group
                                        security_groups=[load_balancer_security_group.id],
                                        subnets=public_subnet_ids,  # Specify public subnets
                                )
    

    # Create the Target Group
    target_group = pulumi_aws.lb.TargetGroup("web-app-target-group",
                                        port=3000,
                                        protocol="HTTP",
                                        target_type="instance",
                                        vpc_id=vpc.id,
                                        health_check={
                                                        "enabled": True,
                                                        "path": "/healthz",  
                                                        "protocol": "HTTP",
                                                        "port": "3000",
                                                        "interval": 30,
                                                        "timeout": 5,
                                                        "healthy_threshold": 2,
                                                        "unhealthy_threshold": 2,
                                                    },
                                                    tags={
                                                        "Name": "web-app-target-group",
                                                    }

                                    )
    

    # Attach the Target Group to the Auto Scaling Group
    # attachment = autoscaling.Attachment("asg-attachment",
    #                                         autoscaling_group_name=auto_scaling_group.name,
    #                                         target_group_arn=target_group.arn,
    #                                     )


    listener = pulumi_aws.lb.Listener("my-listener",
                      load_balancer_arn=load_balancer.arn,
                      port=80,
                      protocol="HTTP",
                      default_actions=[{
                                            "type": "forward",
                                            "target_group_arn": target_group.arn,
                                        }],
                      )
    
    
    launch_template = ec2.LaunchTemplate(
                                            "webapp-launch-template",
                                            image_id=custom_ami_id,
                                            instance_type="t2.micro",
                                            key_name=key_pair_name,
                                            network_interfaces=[{
                                                                    "associate_public_ip_address": True,
                                                                    "security_groups": [app_security_group.id],
                                                                }],
                                            user_data=encoded_userdata,
                                            block_device_mappings=[{
                                                                        "device_name": "/dev/xvda",  # AMI's root device name
                                                                        "ebs": {
                                                                            "volume_size": 25,
                                                                            "volume_type": "gp2",
                                                                            "delete_on_termination": True,
                                                                        },
                                                                    }], 
                                            # security_group_names=[app_security_group.name],
                                            tag_specifications=[{
                                                "resource_type": "instance",
                                                "tags": {
                                                    "Name": "webapp-instance",
                                                },
                                            }],
                                        )

    
    auto_scaling_group = autoscaling.Group("asg",
                                                # launch_configuration=launch_config.id,
                                                launch_template={
                                                                    "id": launch_template.id,
                                                                    "version": "$Latest",  
                                                                },
                                                target_group_arns=[target_group.arn],
                                                vpc_zone_identifiers=public_subnet_ids,
                                                min_size=1,
                                                max_size=3,
                                                desired_capacity=1,
                                                default_cooldown=60,
                                                # health_check_type="EC2",
                                                # health_check_grace_period=300,
                                                # force_delete=True,
                                                tags=[{
                                                    "key": "AutoScalingGroup",
                                                    "value": "true",
                                                    "propagate_at_launch": True,
                                                }],
                                            )
    
    
    scale_up_policy = autoscaling.Policy("scale-up-policy",
                                        scaling_adjustment=1,  # Increment by 1
                                        adjustment_type="ChangeInCapacity",
                                        cooldown=60,  # Cooldown period in seconds
                                        autoscaling_group_name=auto_scaling_group.name,
                                        policy_type="SimpleScaling",
                                        )
    

    
    scale_down_policy = autoscaling.Policy("scale-down-policy",
                                        scaling_adjustment=-1,  # Decrement by 1
                                        adjustment_type="ChangeInCapacity",
                                        cooldown=60,  # Cooldown period in seconds
                                        autoscaling_group_name=auto_scaling_group.name,
                                        policy_type="SimpleScaling",
                                        )
    
    
    alarm_cpuhigh = pulumi_aws.cloudwatch.MetricAlarm("CPU-HIGH",
                                                        comparison_operator="GreaterThanThreshold",
                                                        evaluation_periods=2,
                                                        metric_name="CPU-Utilization",
                                                        namespace="AWS/EC2",
                                                        period=60,
                                                        statistic="Average",
                                                        threshold=25.0,
                                                        alarm_actions=[scale_up_policy.arn],
                                                        dimensions={"AutoScalingGroupName": auto_scaling_group.name},
                                                    )

    alarm_cpulow = pulumi_aws.cloudwatch.MetricAlarm("CPU-LOW",
                                                        comparison_operator="LessThanThreshold",
                                                        evaluation_periods=2,
                                                        metric_name="CPU-Utilization",
                                                        namespace="AWS/EC2",
                                                        period=60,
                                                        statistic="Average",
                                                        threshold=5.0,
                                                        alarm_actions=[scale_down_policy.arn],
                                                        dimensions={"AutoScalingGroupName": auto_scaling_group.name},
                                                    )
    
    

    # Attach the Target Group to the Auto Scaling Group
    # attachment = lb.TargetGroupAttachment("asg-attachment",
    #                                   target_group_arn=target_group.arn,
    #                                   target_id=auto_scaling_group.id,
    #                                   port=80,
    #                                   )
    
    

    # listener_arn = listener.arn




    
    pulumi.export("load_balancer_dns_name", load_balancer.dns_name)


    

    ec2_role = pulumi_aws.iam.Role('ec2Role',
                                   assume_role_policy="""{
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "sts:AssumeRole",
                "Effect": "Allow",
                "Principal": {
                    "Service": "ec2.amazonaws.com"
                }
            }]
        }"""
                                   )
    
    # Attach the AWS-managed CloudWatchAgentServer policy to the role
    policy_attachment = pulumi_aws.iam.RolePolicyAttachment('CloudWatchAgentServerPolicyAttachment',
                                                            role=ec2_role.name,
                                                            policy_arn='arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy')

    # Create an Instance Profile for the role
    instance_profile = pulumi_aws.iam.InstanceProfile(
        'ec2InstanceProfile', role=ec2_role.name)

    # ec2_instance = ec2.Instance("ec2-instance",
    #                             ami=custom_ami_id,
    #                             instance_type="t2.micro",
    #                             subnet_id=public_subnets[0].id,
    #                             security_groups=[app_security_group.id],
    #                             key_name=key_pair_name,  
    #                             iam_instance_profile=instance_profile.name,

    #                             associate_public_ip_address=True,
    #                             tags={
    #                                 "Name": "MyEC2Instance",
    #                             },
    #                             root_block_device=ec2.InstanceRootBlockDeviceArgs(
    #                                 volume_size=25,
    #                                 volume_type='gp2',
    #                                 delete_on_termination=True,
    #                             ),
    #                             disable_api_termination=False,
    #                             user_data=user_data
    #                             )
    ec2.SecurityGroupRule("ec2-to-rds-outbound-rule",
                          type="egress",
                          from_port=3306,             # Source port
                          to_port=3306,               # Destination port
                          protocol="tcp",
                          # Reference to the RDS security group
                          source_security_group_id=rds_security_group.id,
                          security_group_id=app_security_group.id
                          )

    ec2.SecurityGroupRule("ec2-to-internet-https-outbound-rule",
                          type="egress",
                          from_port=443,               # Source port for HTTPS
                          to_port=443,                 # Destination port for HTTPS
                          protocol="tcp",
                          # Allow to all IP addresses
                          cidr_blocks=["0.0.0.0/0"],
                          security_group_id=app_security_group.id
                          )


except ValueError as e:
    # Handle the exception
    print(f"An error occurred: {e}")
pulumi.export('vpc_id', vpc.id)


route53_client = boto3.client("route53")

domain_name = host_name  

# Get the hosted zone ID dynamically based on the domain name
route53_zone = pulumi_aws.route53.get_zone(name=domain_name)

a_record = pulumi_aws.route53.Record("web-app-a-record",
    name=domain_name,
    type="A",
    aliases=[{
        "name": load_balancer.dns_name,
        "zoneId": load_balancer.zone_id,
        "evaluateTargetHealth": False,
    }],
    zone_id=route53_zone.zone_id,
)

# Exporting EC2 instance's public IP and the Route 53 A record
# pulumi.export("ec2_instance_public_ip", ec2_instance.public_ip)
# pulumi.export("route53_a_record", a_record.fqdn)
pulumi.export("web_app_dns_name", a_record.fqdn)


pulumi.export("load_balancer_security_group_id", load_balancer_security_group.id)





# sudo systemctl daemon-reload
# sudo systemctl enable app
# sudo systemctl start app
